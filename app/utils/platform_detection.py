"""Platform detection (spec section 4.3, Analysis Service).

Ported from the Flask generator's `_detect_platforms`. Two complementary
signals: obvious markers in the rendered HTML (CDN hosts, framework strings)
and the names of the ids/classes themselves. The second matters for JS-rendered
shopfronts whose shell carries no CDN reference: if a page's ids are mostly
`shopify-section-*`, it is a Shopify store regardless of markers.

Detection is cumulative -- a site can be several platforms at once (e.g.
WordPress hosting an Elementor theme).
"""

from __future__ import annotations

from typing import Sequence

from bs4 import BeautifulSoup

from app.config.settings import get_settings


def _platform_markers() -> dict[str, tuple[str, ...]]:
    """Raw-HTML markers that identify a platform at a glance."""
    return {
        "shopify": (
            "cdn.shopify.com",
            "shopify-section",
            "myshopify",
            "window.shopify",
            "shopify.shop",
            "sdks.shopifycdn",
        ),
        "betterdocs": ("betterdocs",),
        "elementor": ("elementor-widget", "elementor-element", "elementor-kit"),
    }


def platform_elements_to_remove() -> dict[str, list[str]]:
    """Selectors to strip for each known platform."""
    return {
        "shopify": [
            '[id^="shopify-section-"]',
            '[id^="shopify-section-mini-cart"]',
            "cart-drawer",
            "store-header",
            "product-meta__aside",
            "product-sticky-form",
            "product-form__payment-container",
        ],
        "betterdocs": [
            "betterdocs-entry-footer",
            "betterdocs-mobile-nav",
            "betterdocs-sidebar-icon",
            "betterdocs-category-items-counts",
            "betterdocs-docs-navigation",
        ],
        "elementor": [
            ".elementor-pagination",
            ".elementor-shape-bottom",
            ".elementor-button-text",
            ".elementor-widget-breadcrumbs",
        ],
    }


def detect_platforms(html_pieces: Sequence[str]) -> list[str]:
    """Which known platforms the sampled (rendered) HTML belongs to.

    Returns a sorted list of platform names.
    """
    detected: set[str] = set()
    shopify_section_ids = 0

    for html in html_pieces:
        if not html:
            continue
        lowered = html.lower()
        for platform, markers in _platform_markers().items():
            if any(marker in lowered for marker in markers):
                detected.add(platform)

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            continue

        for el in soup.find_all(True):
            el_id = el.get("id")
            if isinstance(el_id, str) and el_id.strip().lower().startswith("shopify-section"):
                shopify_section_ids += 1
            for cls in el.get("class") or []:
                if not isinstance(cls, str):
                    continue
                lowered_cls = cls.lower()
                if "betterdocs" in lowered_cls:
                    detected.add("betterdocs")
                elif "elementor-widget" in lowered_cls or "elementor-element" in lowered_cls:
                    detected.add("elementor")

    # Several shopify-section ids (not just one coincidence) seals it even when
    # the rendered HTML hides every CDN/marker string.
    if shopify_section_ids >= 2:
        detected.add("shopify")

    return sorted(detected)


def platforms_for_rendered(rendered_pages: Sequence[dict]) -> list[str]:
    """Detect platforms from a batch of rendered page dicts ({html: ...})."""
    return detect_platforms([page.get("html") or "" for page in rendered_pages])