"""Content guard (invariant-based selector pruning).

The whole config is a list of CSS selectors to remove. Naive removal has no
notion of "this element contains the page's real content", so *any* new site
layout can hide content under a selector we emit -- and `el.remove()` takes
every descendant with it (the quitci.com `[id^="shopify-section-"]` case where a
structured-as-sections theme put the product text *inside* a section).

This module turns that into a universal invariant enforced at generation time:

  An element is removable only if removing it does not strip the page's content.

It works on the already-rendered HTML (BeautifulSoup), so it needs no extra
network or browser. For each candidate selector it answers two questions:

1. Destructive?  removing it strips the page's text down past a floor.
2. Explodable?   if it is destructive but only *some* of its matched elements
                 are, narrow it to exact safe sub-selectors (#id / tag) instead
                 of dropping all of it.

A final integrity pass re-checks the *combined* kept list, so even many small
"safe" selectors can never jointly nuke a page.

Because the rule is derived from the live DOM and identical for every site, it
generalizes to Shopify, WordPress, custom SPAs, and anything else -- no per-site
rules, no whack-a-mole.
"""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

from bs4 import BeautifulSoup, Tag

from app.config.settings import get_settings
from app.utils import safety_guards

logger = logging.getLogger(__name__)

# The floor below which a page has been stripped of its answerable content.
# Mirrors the validator's per-page requirement (content > 500 chars).
_MIN_TEXT = 500

# Selectors that are almost certainly the content region itself, never boilerplate.
_CONTENT_CONTAINER_SELECTORS = frozenset({
    "main",
    ".main",
    "#main",
    ".site-main",
    ".page-content",
    "#page-content",
    ".content",
    "#content",
    "#page",
    "article",
    "body",
    "html",
})

# A matched element gets an exact selector only if it can be addressed specifically;
# generic div/span/section carriers are skipped (we drop them, never emit `div`).
_GENERIC_TAGS = frozenset({"div", "span", "body", "html", "section"})


def is_content_container(selector: str) -> bool:
    """True when a selector targets the content region and should never be emitted."""
    if not selector or not isinstance(selector, str):
        return False
    candidate = selector.strip().lower().lstrip(" *")
    return candidate in _CONTENT_CONTAINER_SELECTORS


def _parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def _text_len(soup: BeautifulSoup) -> int:
    return len(soup.get_text("", strip=True))


def _clone(html: str) -> BeautifulSoup:
    """A fresh parse is required; bs4 trees cannot be re-attached."""
    return _parse(html)


def _removing_keeps_text(html: str, selectors: Iterable[str], min_text: int) -> bool:
    """Remove all matches and return whether at least `min_text` chars survive."""
    soup = _clone(html)
    for sel in set(selectors):
        try:
            for el in soup.select(sel):
                el.decompose()
        except Exception:
            return False
    return _text_len(soup) >= min_text


def _exact_selector(el: Tag) -> str | None:
    """A precise, tame CSS selector addressing `el` (prefer id, then a semantic tag)."""
    el_id = el.get("id")
    if isinstance(el_id, str) and el_id.strip():
        candidate = "#" + el_id.strip()
        if safety_guards.is_safe_selector(candidate):
            return candidate
    name = el.name
    if name and name not in _GENERIC_TAGS and ":" not in name and safety_guards.is_safe_selector(name):
        return name
    return None


def _prune_selector(html: str, selector: str, min_text: int) -> tuple[list[str], bool]:
    """Apply the invariant to one page for one selector.

    Returns (exact_safe_selectors_to_keep, was_destructive). A page where the
    selector does not match counts as safe and contributes nothing.
    """
    soup = _parse(html)
    try:
        matched = soup.select(selector)
    except Exception:
        return [selector], False
    if not matched:
        return [], False

    # Nothing substantive on the page to protect -- leave the selector alone.
    if _text_len(soup) < min_text:
        return [selector], False

    # Whole selector: does removing everything it matches nuke the page?
    if _removing_keeps_text(html, [selector], min_text):
        return [], False  # safe as-is

    # Destructive as a whole -- narrow to the individual matches that are safe.
    # Element identity does not survive a re-parse, but document order does, so
    # probe each match by its index in the stable match set.
    kept: list[str] = []
    safe_indices = _safe_match_indices(html, selector, matched, min_text)
    for i, el in enumerate(matched):
        if i not in safe_indices:
            continue
        exact = _exact_selector(el)
        if exact and exact not in kept:
            kept.append(exact)
    return kept, True


def _safe_match_indices(html: str, selector: str, matched: list, min_text: int) -> set[int]:
    """Indices of the matched elements whose removal *alone* keeps the text intact."""
    safe: set[int] = set()
    for i in range(len(matched)):
        probe = _clone(html)
        probe_matches = probe.select(selector)
        if i < len(probe_matches):
            probe_matches[i].decompose()
        if _text_len(probe) >= min_text:
            safe.add(i)
    return safe


def prune_elements(
    htmls: Sequence[str],
    elements: Iterable[str],
    min_text: int | None = None,
) -> dict:
    """Content-guard a selector list across rendered pages.

    Returns {"kept": [...], "dropped": [{"selector","reason","safe"}], "counts": {...}}.
    """
    min_text = min_text or _MIN_TEXT
    samples = [h for h in htmls if h]

    kept: list[str] = []
    dropped: list[dict] = []

    for raw in elements:
        if not isinstance(raw, str):
            continue
        selector = raw.strip()
        if not selector or selector in kept:
            continue
        if is_content_container(selector):
            dropped.append({"selector": selector, "reason": "targets the content region"})
            continue

        was_destructive = False
        safe_exacts: list[str] = []
        for html in samples:
            exacts, destructive = _prune_selector(html, selector, min_text)
            if destructive:
                was_destructive = True
                for e in exacts:
                    if e not in safe_exacts:
                        safe_exacts.append(e)

        if was_destructive:
            if safe_exacts:
                kept.extend(safe_exacts)
                dropped.append({
                    "selector": selector,
                    "reason": "narrowed to exact matches that do not contain content",
                    "safe": safe_exacts,
                })
            else:
                dropped.append({"selector": selector, "reason": "removes the page content"})
        else:
            kept.append(selector)

    kept = _integrity_pass(samples, kept, min_text, dropped)

    seen: set[str] = set()
    final_kept: list[str] = []
    for sel in kept:
        if sel not in seen:
            seen.add(sel)
            final_kept.append(sel)

    return {
        "kept": final_kept,
        "dropped": dropped,
        "counts": {"kept": len(final_kept), "dropped": len(dropped)},
    }


def _integrity_pass(
    htmls: Sequence[str],
    kept: list[str],
    min_text: int,
    dropped: list[dict],
) -> list[str]:
    """Iteratively trim selectors that, combined, strip a page below the floor."""
    working = list(kept)
    for html in htmls:
        if not working:
            break
        # Pages already below the floor have nothing worth protecting.
        if _text_len(_parse(html)) < min_text:
            continue
        while not _removing_keeps_text(html, working, min_text):
            widow = _max_widower(html, working)
            if not widow:
                break
            working.remove(widow)
            if not any(d["selector"] == widow for d in dropped):
                dropped.append({"selector": widow, "reason": "dropped so content survives the page"})
    return working


def _max_widower(html: str, selectors: list[str]):
    """The selector that, when kept in the list, retains the most page text.

    Removing it from the config lets that text survive -- the biggest culprit.
    """
    best = None
    best_text = -1
    for sel in selectors:
        kept = _clone(html)
        for other in selectors:
            if other == sel:
                continue
            try:
                for el in kept.select(other):
                    el.decompose()
            except Exception:
                continue
        retained = _text_len(kept)
        if retained > best_text:
            best_text = retained
            best = sel
    return best if best_text >= 0 else None