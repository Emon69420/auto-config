"""LLM compiler service (spec section 4.4) - LLMCompiler.

Turns the inventory, platforms, and structured data into the per-site part of a
config: which selectors are site-wide boilerplate, and which paths are not
content. All output passes through the shared safety guard before it is usable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Sequence

from app.config.prompts import build_compiler_prompt
from app.config.settings import get_settings
from app.models.selector import SelectorInventory
from app.services import llm_client
from app.utils import safety_guards
from app.utils.url_normalizer import get_path_segments

logger = logging.getLogger(__name__)

_PATH_RE = re.compile(r"^/[a-zA-Z0-9\-_./ ]*$")


def _format_counted(items: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(items.items(), key=lambda kv: (-kv[1], kv[0]))


def _json_ld_summary(blobs: Sequence[dict]) -> str:
    from collections import Counter

    types = Counter()
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        label = blob.get("@type") or blob.get("@context") or "unknown"
        types[str(label)] += 1
    return ", ".join(f"{label} x{count}" for label, count in types.most_common(10))


def _clean_paths(items) -> list[str]:
    """Keep only tame, absolute path-like entries from LLM output."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items or []:
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if candidate in seen or not _PATH_RE.match(candidate):
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


class LLMCompiler:
    """Uses Gemini to convert analysis output into config decisions."""

    def compile_config(
        self,
        url: str,
        platforms: list[str],
        inventory: SelectorInventory,
        json_ld_blobs: Sequence[dict],
        num_pages: int,
        sample_html: str,
    ) -> dict[str, list[str]]:
        """Return {'elementsToRemove': [...], 'pathsToSkip': [...]} (spec 4.4)."""
        settings = get_settings()

        prompt = build_compiler_prompt(
            url=url,
            platforms=list(platforms),
            num_pages=max(1, num_pages),
            inventory_ids=_format_counted(inventory.ids),
            inventory_classes=_format_counted(inventory.classes),
            inventory_tags=_format_counted(inventory.tags),
            json_ld_summary=_json_ld_summary(json_ld_blobs),
            sample_html_fragment=(sample_html or "")[: settings.html_fragment_chars],
        )

        raw = llm_client.llm_complete(prompt, json_mode=True)
        payload = self._parse_payload(raw)

        elements = safety_guards.filter_safe_selectors(
            payload.get("elementsToRemove", []),
            cap=settings.max_ai_selectors,
        )
        paths = _clean_paths(payload.get("pathsToSkip", []))
        return {"elementsToRemove": elements, "pathsToSkip": paths}

    def _parse_payload(self, raw: str | None) -> dict:
        """Extract the compiler payload from the raw LLM JSON text."""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM compiler returned unparseable JSON: %.200s", raw)
            return {}
        if isinstance(parsed, list):
            return {"elementsToRemove": parsed, "pathsToSkip": []}
        if isinstance(parsed, dict):
            return parsed
        return {}