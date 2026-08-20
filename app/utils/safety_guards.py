"""Safety guards for LLM- and platform-derived selectors.

Ported from the Flask generator. Two layers:

1. `is_safe_selector` - rejects anything that is not a short, tame CSS selector
   (no javascript:, braces, parens, or oversized strings). Accepts ids, classes,
   bare custom-element tags, and attribute selectors.
2. `is_utility_class` - refuses framework scaffolding that recurs on every page
   precisely because it styles content. Stripping these would hide or remove the
   very text the chatbot answers from, so we refuse them outright rather than
   trust the LLM.

`pick_safe_selectors` is the single choke point that dedups, filters, and caps
any candidate list before it can reach a config.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from app.config.settings import get_settings

_SAFE_SELECTOR_RE = re.compile(r"^[\w#.:\-\[\]=\^$\"'*+~> ,]+$")

_UTILITY_CLASSES = frozenset({
    "d-flex", "d-block", "d-none", "d-inline", "d-inline-block", "d-grid",
    "d-table", "d-contents",
    "flex-row", "flex-column", "flex-wrap", "flex-nowrap", "flex-grow-1",
    "flex-shrink-1",
    "align-items-center", "align-items-start", "align-items-end",
    "justify-content-between", "justify-content-center", "justify-content-start",
    "justify-content-end", "justify-content-around",
    "align-self-center", "align-self-start", "align-self-end",
    "font-bold", "font-normal", "font-medium", "font-semibold", "font-light",
    "font-thin", "font-weight-bold", "fw-bold",
    "text-center", "text-left", "text-right",
    "float-right", "float-left", "float-none",
    "position-relative", "position-absolute", "position-fixed", "position-sticky",
    "w-100", "w-50", "h-100",
    "m-0", "mt-0", "mb-0", "ml-0", "mr-0", "p-0", "pt-0", "pb-0", "pl-0", "pr-0",
    # Bootstrap layout/image scaffolding: stripping these would break the whole
    # page (container/row/col) or every <img> (img-fluid/rounded).
    "container", "container-fluid", "container-sm", "container-md",
    "container-lg", "container-xl", "container-xxl",
    "row", "col", "col-auto",
    "img-fluid", "img-thumbnail", "rounded", "rounded-circle", "rounded-pill",
    "visible", "invisible",
})

_UTILITY_CLASS_RE = re.compile(
    r"^(?:"
    r"[mp](?:[trblxy])?-[a-z0-9]+"
    r"|g(?:x|y)?-[a-z0-9]+"
    r"|d-(?:[a-z]{2})?-?(?:flex|block|inline|none|grid|table|contents)"
    r"|(?:fw|font|text|float)-[a-z0-9-]+"
    r"|align-(?:items|self)-[a-z0-9-]+"
    r"|justify-content-[a-z0-9-]+"
    r"|col-[a-z0-9-]+"
    r"|img-(?:fluid|thumbnail)"
    r"|rounded(?:-[a-z0-9-]+)?"
    r")$",
    re.IGNORECASE,
)


def is_safe_selector(selector: str) -> bool:
    """True when a selector is safe to include in a config.

    A selector must be a short, tame CSS selector: id, class, attribute selector
    or a bare element tag (custom elements may carry dashes/underscores). It is
    rejected when it could be a URL, javascript:, arbitrary code, a class-list,
    or a framework utility class.
    """
    if not selector or not isinstance(selector, str):
        return False
    candidate = selector.strip()
    if len(candidate) > 200 or not _SAFE_SELECTOR_RE.match(candidate):
        return False
    if "javascript:" in candidate.lower() or "{" in candidate or "(" in candidate:
        return False
    if not re.search(r"[#.\[]", candidate) and not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", candidate):
        return False
    if candidate.startswith(("#", ".")) and " " in candidate:
        return False
    if is_utility_class(candidate):
        return False
    return True


def is_utility_class(selector: str) -> bool:
    """True when a class selector is framework scaffolding, not a content block.

    Matched by name and by family (m-*, p-*, col-*, d-*, ...) so new breakpoint
    or scale steps are refused without enumerating them.
    """
    if not selector.startswith("."):
        return False
    name = selector[1:]
    return name in _UTILITY_CLASSES or bool(_UTILITY_CLASS_RE.match(name))


def filter_safe_selectors(
    selectors: Iterable[str],
    *,
    exclude: set[str] | None = None,
    cap: int | None = None,
) -> list[str]:
    """Dedup, validate, and cap a list of candidate selectors.

    This is the single choke point every selector source passes through
    (platform table, LLM compiler, healer), so unsafe or duplicate selectors can
    never reach a config by any path.
    """
    seen: set[str] = set(exclude) if exclude is not None else set()
    out: list[str] = []
    for raw in selectors:
        if not isinstance(raw, str):
            continue
        selector = raw.strip()
        if not selector or selector in seen:
            continue
        if not is_safe_selector(selector):
            continue
        seen.add(selector)
        out.append(selector)
        if cap is not None and len(out) >= cap:
            break
    return out