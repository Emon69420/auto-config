"""Unit tests for the content guard (invariant-based selector pruning).

The guard's job: a selector list must never, in combination, strip a page's
content. It drops/narrows destructive selectors using only the rendered HTML.
"""

from app.services.content_guard import (
    is_content_container,
    prune_elements,
)

_LONG = "answerable product description text. " * 250  # ~15k chars, well > floor


def _content_in_section_html():
    """quitci.com-style: the product content lives INSIDE a shopify-section."""
    return f"""
    <body>
      <div id="shopify-section-announcement">Announcement bar</div>
      <div id="shopify-section-header"><nav>Home Products About</nav></div>
      <div id="shopify-section-main"><div class="product">{_LONG}</div></div>
      <div id="shopify-section-footer"><footer>Footer links</footer></div>
      <div id="shopify-section-cart-drawer"><div>cart overlay</div></div>
    </body>
    """


def _content_outside_section_html():
    """ivfmatters-style: content in a real <main>, sections are only chrome."""
    return f"""
    <body>
      <header id="shopify-section-header">Header text</header>
      <main class="product"><div class="product-info">{_LONG}</div></main>
      <footer id="shopify-section-footer">Footer text</footer>
    </body>
    """


def test_narrows_broad_selector_when_content_lives_in_section():
    html = _content_in_section_html()
    elements = [
        '[id^="shopify-section-"]',
        "nav",
        "header",
        "footer",
        ".fixed",
        "#cart-notification",
        "main",
        "body",
    ]
    result = prune_elements([html], elements)

    kept = result["kept"]
    # the broad catch-all is narrowed, not emitted raw
    assert '[id^="shopify-section-"]' not in kept
    # the content-bearing section is never kept
    assert "#shopify-section-main" not in kept
    # the safe chrome sections survive as exact ids
    assert "#shopify-section-header" in kept
    assert "#shopify-section-footer" in kept
    assert "#shopify-section-cart-drawer" in kept
    # content containers are always refused
    assert "main" not in kept
    assert "body" not in kept
    # plain chrome selectors survive
    assert "nav" in kept

    narrowed = next(d for d in result["dropped"] if d["selector"] == '[id^="shopify-section-"]')
    assert "#shopify-section-main" not in narrowed.get("kept", [])


def test_keeps_broad_selector_when_content_is_outside_sections():
    html = _content_outside_section_html()
    elements = ['[id^="shopify-section-"]', "header", "footer", "main", ".product"]
    result = prune_elements([html], elements)

    kept = result["kept"]
    assert '[id^="shopify-section-"]' in kept
    assert "header" in kept
    assert "footer" in kept
    assert "main" not in kept
    assert ".product" not in kept


def test_tiny_page_is_left_alone():
    html = "<body><div id='shopify-section-header'>x</div><footer>f</footer></body>"
    elements = ['[id^="shopify-section-"]', "footer"]
    result = prune_elements([html], elements)
    # nothing substantive to protect, so the list is untouched (no spurious drops)
    assert result["kept"] == ['[id^="shopify-section-"]', "footer"]
    assert not result["dropped"]


def test_combined_kept_list_never_nukes_content():
    # several individually-safe chrome selectors must not jointly strip content
    html = _content_in_section_html()
    elements = [
        "nav",
        "header",
        "footer",
        "[id^='shopify-section-']",
    ]
    result = prune_elements([html], elements)
    # re-apply the full kept list to the page and ensure content survives
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for sel in result["kept"]:
        for el in soup.select(sel):
            el.decompose()
    assert len(soup.get_text("", strip=True)) >= 500


def test_is_content_container_refuses_mainlike_selectors():
    for sel in ["main", ".main", "#main", ".site-main", ".content", "#content", "body", "article"]:
        assert is_content_container(sel) is True
    for sel in ["nav", "header", "footer", "#sidebar", "[id^='shopify-section-']"]:
        assert is_content_container(sel) is False


def _two_content_sections_html():
    """Two sections carry content: a single-section deletion still leaves text,
    so the narrow step deems each individually safe -- the integrity pass must
    then reconcile the report to avoid 'kept then dropped' contradictions."""
    long_a = "content section A text. " * 300
    long_b = "content section B text. " * 300
    return f"""
    <body>
      <div id="shopify-section-header">Header nav</div>
      <div id="shopify-section-main-a">{long_a}</div>
      <div id="shopify-section-main-b">{long_b}</div>
      <footer>footer</footer>
    </body>
    """


def test_report_is_reconciled_after_integrity_pass():
    html = _two_content_sections_html()
    result = prune_elements([html], ['[id^="shopify-section-"]'])

    kept = set(result["kept"])
    broad_entries = [d for d in result["dropped"] if d["selector"] == '[id^="shopify-section-"]']
    assert len(broad_entries) == 1  # reported exactly once
    entry = broad_entries[0]

    # nothing is advertised as "kept" that did not survive the integrity pass
    for sel in entry.get("kept", []):
        assert sel in kept
    # no selector is both "kept" and separately listed as a dropped entry
    for d in result["dropped"]:
        assert d["selector"] not in kept
    # content survives once the final kept list is applied
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for sel in result["kept"]:
        for el in soup.select(sel):
            el.decompose()
    assert len(soup.get_text("", strip=True)) >= 500