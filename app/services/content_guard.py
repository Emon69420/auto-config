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

    Returns {"kept": [...], "dropped": [{"selector","reason","kept?"}], "counts": {...}}.
    A narrowing entry carries the surviving exact matches under "kept"; entries
    already reflect the final state after the integrity pass, so a selector is
    never listed as kept and then separately dropped.
    """
    min_text = min_text or _MIN_TEXT
    samples = [h for h in htmls if h]

    kept: list[str] = []
    dropped: list[dict] = []
    # sel -> the broad selector that produced it (provenance for reconciliation)
    narrow_source: dict[str, str] = {}
    # broad selectors that got narrowed and need their report finalized later
    narrowed: list[str] = []

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
                narrowed.append(selector)
                for e in safe_exacts:
                    narrow_source[e] = selector
            else:
                dropped.append({"selector": selector, "reason": "removes the page content"})
        else:
            kept.append(selector)

    final_kept, integrity_dropped = _integrity_pass(samples, kept, min_text)

    # Reconcile the report so nothing is listed as kept that did not survive the
    # integrity pass, and nothing is both "kept" and separately "dropped".
    final_kept = _dedupe(final_kept)
    final_dropped: list[dict] = []
    for entry in dropped:
        if entry["selector"] not in {d["selector"] for d in final_dropped}:
            final_dropped.append(entry)

    for broad in narrowed:
        kept_here = [s for s in final_kept if narrow_source.get(s) == broad]
        if kept_here:
            final_dropped.append({
                "selector": broad,
                "reason": "narrowed to exact matches that do not contain content",
                "kept": kept_here,
            })
        else:
            final_dropped.append({"selector": broad, "reason": "removes the page content"})

    for sel in integrity_dropped:
        # selectors dropped by integrity that came from a narrow are already
        # reflected in that narrow's final "kept" list -- report them once.
        if sel in narrow_source:
            continue
        if not any(d["selector"] == sel for d in final_dropped):
            final_dropped.append({"selector": sel, "reason": "dropped so content survives the page"})

    return {
        "kept": final_kept,
        "dropped": final_dropped,
        "counts": {"kept": len(final_kept), "dropped": len(final_dropped)},
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sel in items:
        if sel not in seen:
            seen.add(sel)
            out.append(sel)
    return out


def _integrity_pass(
    htmls: Sequence[str],
    kept: list[str],
    min_text: int,
) -> tuple[list[str], list[str]]:
    """Trim selectors that, combined, strip a page below the floor.

    Returns (surviving selectors, selectors removed by the pass).
    """
    working = list(kept)
    removed: list[str] = []
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
            removed.append(widow)
    return working, removed


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