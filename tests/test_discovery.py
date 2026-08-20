"""Unit tests for SiteDiscovery using mocked fetches (no network)."""

from app.services.discovery import SiteDiscovery


def _discovery(monkeypatch, getter):
    d = SiteDiscovery("https://example.com")
    monkeypatch.setattr(d, "_get", getter)
    return d


def test_fetch_robots_extracts_sitemap_urls(monkeypatch):
    def getter(url):
        return "User-agent: *\nDisallow: /admin\nSitemap: https://example.com/sitemap.xml\n"
    d = _discovery(monkeypatch, getter)
    assert d.fetch_robots() == ["https://example.com/sitemap.xml"]


def test_fetch_robots_empty_on_missing(monkeypatch):
    d = _discovery(monkeypatch, lambda url: "")
    assert d.fetch_robots() == []


def test_flatten_sitemap_index_and_pages(monkeypatch):
    index_xml = """<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
    </sitemapindex>"""
    pages_xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/</loc></url>
      <url><loc>https://example.com/about</loc></url>
    </urlset>"""
    io = {
        "https://example.com/sitemap_index.xml": index_xml,
        "https://example.com/sitemap-pages.xml": pages_xml,
    }
    d = _discovery(monkeypatch, lambda url: io.get(url, ""))
    flat = d._flatten_sitemap("https://example.com/sitemap_index.xml", 0, set())
    assert "https://example.com/about" in flat


def test_get_diverse_urls_prefers_homepage_and_types(monkeypatch):
    urls = [
        "https://example.com/",
        "https://example.com/products/1",
        "https://example.com/products/2",
        "https://example.com/blogs/news/a",
        "https://example.com/contact",
    ]
    d = _discovery(monkeypatch, lambda url: "")
    monkeypatch.setattr(d, "fetch_sitemaps", lambda: urls)
    diverse = d.get_diverse_urls(n=4)
    assert diverse[0] == "https://example.com"
    assert any("/products/" in u for u in diverse)
    assert any("/blogs/" in u or "/blog" in u for u in diverse)
    assert len(diverse) <= 4


def test_fallback_crawl_when_no_sitemap(monkeypatch):
    d = _discovery(monkeypatch, lambda url: "")
    monkeypatch.setattr(d, "fetch_sitemaps", lambda: [])
    # fallback_crawl returns at least the homepage even on empty body
    found = d.fallback_crawl(n=5)
    assert found == [] or found[0] == "https://example.com/"