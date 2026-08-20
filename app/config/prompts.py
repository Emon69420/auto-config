"""LLM prompt templates for the scraper-config-generator.

Both prompts are kept as functions that take structured data and return the
prompt string. The language here follows the specification closely:

- LLM Compiler prompt: spec section 4.4
- Auto-healer prompt:   spec section 4.6
"""

from __future__ import annotations


def build_compiler_prompt(
    url: str,
    platforms: list[str],
    num_pages: int,
    inventory_ids: list[tuple[str, int]],
    inventory_classes: list[tuple[str, int]],
    inventory_tags: list[tuple[str, int]],
    json_ld_summary: str,
    sample_html_fragment: str,
) -> str:
    """Build the prompt that turns a selector inventory into a config.

    The model picks site-wide boilerplate from the inventory actually observed
    on the rendered pages. It is constrained to selectors that appear on every
    sampled page, forbidden from utility/content classes, and capped at 15
    selectors (spec section 4.4).
    """
    return f"""
You are a web scraping configuration generator.

Website: {url}
Platforms detected: {", ".join(platforms) or "none"}

Selector Inventory (frequency across {num_pages} pages):
IDs:
{_format_inventory(inventory_ids) or "none"}
Classes:
{_format_inventory(inventory_classes) or "none"}
Custom tags:
{format_tags(inventory_tags) or "none"}

Structured data found:
{json_ld_summary or "none"}

SAMPLE PAGE FRAGMENT:
{sample_html_fragment}

TASK: Identify site-wide boilerplate that appears on EVERY page:
- Navigation (header, menu, nav bars)
- Footer (links, copyright, social icons)
- Reappearing CTAs (sticky buttons, popups, banners)
- Forms (newsletter signup, contact forms in sidebar)
- Sidebars (widgets, related links, ads)
- Cookie banners, cookie notices

RULES:
- ONLY include selectors with frequency = {num_pages} (appears on every page)
- DO NOT include utility classes (container, row, col, d-flex, m-*, p-*, text-*, etc.)
- DO NOT include content selectors (products, articles, blog posts)
- Prefer specific selectors over generic ones
- Cap at 15 selectors

Return ONLY valid JSON:
{{
  "elementsToRemove": ["selector1", "selector2", ...],
  "pathsToSkip": ["/admin", "/cart", ...]
}}
""".strip()


def build_heal_prompt(
    broken_selector: str,
    field_name: str,
    dom_snapshot: str,
) -> str:
    """Build the prompt that proposes a replacement for a broken selector.

    Spec section 4.6.
    """
    return f"""
The selector "{broken_selector}" no longer works for {field_name}.

Current page HTML:
{dom_snapshot}

Propose a new CSS selector that will reliably target {field_name}.
Return ONLY the selector.
""".strip()


def format_tags(tags: list[tuple[str, int]]) -> str:
    """Format tag names for the prompt (they are bare elements, not selectors)."""
    return "\n".join(f"<{name}> : seen {count}x" for name, count in tags)


def _format_inventory(items: list[tuple[str, int]]) -> str:
    return "\n".join(f"{name} : seen {count}x" for name, count in items)