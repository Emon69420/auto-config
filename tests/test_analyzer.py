"""Unit tests for the SelectorAnalyzer."""

from app.services.analyzer import SelectorAnalyzer

HTML = """
<html><head><title>T</title></head><body>
<div id="header" class="wrap nav"><span class="icon">x</span></div>
<div id="main" class="content"><p>Hello world</p><p>More</p></div>
<footer id="footer" class="wrap foot"><nav><a>Link</a></nav></footer>
<script type="application/ld+json">{"@type": "Organization"}</script>
</body></html>
"""


def test_extract_inventory_counts_ids_classes_tags():
    inventory = SelectorAnalyzer().extract_selector_inventory(HTML)
    assert inventory.ids["#header"] == 1
    assert inventory.ids["#footer"] == 1
    assert inventory.classes[".wrap"] == 2
    assert "p" in inventory.tags


def test_aggregate_inventory_sums_across_pages_and_trims():
    rendered = [
        {"url": "https://a.com/1", "html": HTML, "json_ld": [], "og_tags": {}},
        {"url": "https://a.com/2", "html": HTML, "json_ld": [], "og_tags": {}},
    ]
    analyzer = SelectorAnalyzer()
    inventory = analyzer.aggregate_inventory(rendered, settings=None)
    assert inventory.classes[".wrap"] == 4
    assert inventory.total() > 0


def test_extract_json_ld_concatenates():
    rendered = [{"html": HTML, "json_ld": [{"@type": "Organization"}]}]
    blobs = SelectorAnalyzer().extract_json_ld(rendered)
    assert blobs == [{"@type": "Organization"}]


def test_detect_platforms_from_rendered():
    shopify = {'html': "<div id='shopify-section-a'></div><div id='shopify-section-b'></div>"}
    assert SelectorAnalyzer().detect_platforms([shopify]) == ["shopify"]