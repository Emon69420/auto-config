"""Unit tests for platform detection."""

from app.utils import platform_detection as pd


def test_detects_shopify_from_cdn_marker():
    html = '<html><script src="https://cdn.shopify.com/s.js"></script></html>'
    assert pd.detect_platforms([html]) == ["shopify"]


def test_detects_shopify_from_section_ids_even_without_marker():
    html = ("<html><div id='shopify-section-header'></div>"
            "<div id='shopify-section-footer'></div></html>")
    # no CDN marker anywhere
    assert "shopify" not in html.lower().split("cdn.shopify.com")
    assert pd.detect_platforms([html]) == ["shopify"]


def test_single_shopify_section_id_is_detected_via_marker():
    # the string "shopify-section" is itself a marker, so even one id counts
    html = "<html><div id='shopify-section-accidental'></div></html>"
    assert pd.detect_platforms([html]) == ["shopify"]


def test_unrelated_id_does_not_detect_shopify():
    html = "<html><div id='random-unrelated'></div></html>"
    assert pd.detect_platforms([html]) == []


def test_detects_elementor_from_marker():
    html = '<div class="elementor-widget elementor-button"></div>'
    assert "elementor" in pd.detect_platforms([html])


def test_platform_elements_include_shopify_defaults():
    table = pd.platform_elements_to_remove()
    assert '[id^="shopify-section-"]' in table["shopify"]
    assert "cart-drawer" in table["shopify"]
    assert "store-header" in table["shopify"]


def test_multiple_platforms_cumulative():
    html = ('<div class="elementor-widget"></div>'
            '<div id="shopify-section-a" id2=""></div><div id="shopify-section-b"></div>'
            '<script src="https://cdn.shopify.com/x"></script>')
    detected = pd.detect_platforms([html])
    assert "shopify" in detected
    assert "elementor" in detected