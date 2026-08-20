"""Analysis service (spec section 4.3) - SelectorAnalyzer.

Extracts the selector inventory (every id, class, tag with page-frequency across
the rendered samples), the structured data, and the detected platforms.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from bs4 import BeautifulSoup

from app.models.selector import SelectorInventory
from app.utils import platform_detection


class SelectorAnalyzer:
    """Measures what the rendered pages are made of."""

    def extract_selector_inventory(self, html: str) -> SelectorInventory:
        """Count ids, classes, and tags in a single HTML document."""
        ids: Counter[str] = Counter()
        classes: Counter[str] = Counter()
        tags: Counter[str] = Counter()

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return SelectorInventory()

        for el in soup.find_all(True):
            el_tag = el.name
            if el_tag:
                tags[el_tag] += 1
            el_id = el.get("id")
            if isinstance(el_id, str) and el_id.strip():
                ids["#" + el_id.strip()] += 1
            for cls in el.get("class") or []:
                if isinstance(cls, str) and cls.strip():
                    classes["." + cls.strip()] += 1
        return SelectorInventory(ids=dict(ids), classes=dict(classes), tags=dict(tags))

    def aggregate_inventory(
        self,
        rendered_pages: Sequence[dict],
        settings=None,
    ) -> SelectorInventory:
        """Aggregate inventories across pages, keeping the most frequent selectors.

        Counters are accumulated outside the Pydantic model (Pydantic v2 does not
        persist in-place mutation of a model's dict field), then the bounded
        subset is returned so prompts stay small (spec 4.3: ~50 ids/100 classes/20
        tags).
        """
        from app.config.settings import get_settings

        settings = settings or get_settings()
        ids: Counter[str] = Counter()
        classes: Counter[str] = Counter()
        tags: Counter[str] = Counter()
        for page in rendered_pages:
            html = page.get("html") or ""
            if not html:
                continue
            found = self.extract_selector_inventory(html)
            ids.update(found.ids)
            classes.update(found.classes)
            tags.update(found.tags)

        inventory = SelectorInventory(ids=dict(ids), classes=dict(classes), tags=dict(tags))
        return inventory.top(
            ids=settings.inventory_top_ids,
            classes=settings.inventory_top_classes,
            tags=settings.inventory_top_tags,
        )

    def extract_json_ld(self, rendered_pages: Sequence[dict]) -> list[dict]:
        """Concatenate all JSON-LD blobs found across the rendered pages."""
        blobs: list[dict] = []
        for page in rendered_pages:
            for blob in page.get("json_ld") or []:
                if isinstance(blob, dict):
                    blobs.append(blob)
        return blobs

    def detect_platforms(self, rendered_pages: Sequence[dict]) -> list[str]:
        """Which platforms the rendered pages belong to (spec 4.3)."""
        return platform_detection.platforms_for_rendered(rendered_pages)