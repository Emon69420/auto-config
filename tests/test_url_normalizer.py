"""Unit tests for URL normalization helpers."""

from app.utils import url_normalizer as nu


def test_config_filename_keeps_www():
    assert nu.config_filename("https://www.example.com") == "www.example.com.json"


def test_config_filename_strips_scheme_and_path():
    assert nu.config_filename("https://Example.com/some/path?q=1") == "example.com.json"


def test_config_filename_sanitizes_bad_chars():
    assert nu.config_filename("https://EXAMPLE_1.com") == "example_1.com.json"


def test_config_filename_default_for_junk():
    assert nu.config_filename("") == "default.json"


def test_canonicalize_lowercases_and_strips_slash():
    assert nu.canonicalize("HTTPS://EXAMPLE.COM/About/") == "https://example.com/about"


def test_seed_key_dedupes_homepage_forms():
    a = nu.seed_key("https://example.com/")
    b = nu.seed_key("https://example.com")
    assert a == b


def test_get_origin():
    assert nu.get_origin("https://www.example.com:8080/path") == "https://www.example.com:8080"


def test_same_domain():
    assert nu.same_domain("https://a.com/x", "http://a.com/y")
    assert not nu.same_domain("https://a.com/x", "https://b.com/y")


def test_ensure_scheme():
    assert nu.ensure_scheme("example.com") == "https://example.com"
    assert nu.ensure_scheme("http://example.com") == "http://example.com"


def test_get_path_segments_lowercases():
    assert nu.get_path_segments("https://a.com/Category/Products") == ["category", "products"]