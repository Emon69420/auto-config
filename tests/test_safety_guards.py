"""Unit tests for the selector safety guards."""

from app.utils import safety_guards as sg


def test_accepts_simple_selector_types():
    assert sg.is_safe_selector(".slide")
    assert sg.is_safe_selector("#header-main")
    assert sg.is_safe_selector("[id^=shopify-section-]")
    assert sg.is_safe_selector("cart-drawer")


def test_rejects_framework_utilities():
    assert not sg.is_safe_selector(".container")
    assert not sg.is_safe_selector(".img-fluid")
    assert not sg.is_safe_selector(".d-flex")
    assert not sg.is_safe_selector(".justify-content-between")
    assert not sg.is_safe_selector(".m-0")


def test_rejects_dangerous_or_malformed_selectors():
    assert not sg.is_safe_selector("javascript:alert(1)")
    assert not sg.is_safe_selector(".a .b .c .d .e .f .g .h " * 30)  # too long
    assert not sg.is_safe_selector("https://evil.example/x")
    assert not sg.is_safe_selector(".multi word class")


def test_rejects_bare_unknown_words_not_selector_like():
    assert not sg.is_safe_selector("some free text")


def test_filter_safe_selectors_dedups_and_caps():
    out = sg.filter_safe_selectors(
        [".a", ".b", ".a", "nav", ".container", ".c", ".d", ".e"],
        cap=3,
    )
    # .a and .b dedup, .container rejected -> first safe are .a, .b, nav(.c should fit but cap)
    assert ".a" in out and ".b" in out
    assert ".container" not in out
    assert len(out) <= 3


def test_filter_safe_selectors_excludes_existing():
    out = sg.filter_safe_selectors([".a", ".b"], exclude={".a"})
    assert ".a" not in out
    assert ".b" in out