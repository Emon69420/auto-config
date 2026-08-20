"""URL normalization helpers.

Every URL flowing through the pipeline is normalized through these functions so
comparisons, filenames, and seeds are consistent. The filename rules match the
worker's expectations (beyondchats-node/src/scrapers/ReadMe.md): the filename is
the exact host, `www` preserved.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def ensure_scheme(url: str) -> str:
    """Prefix https:// when a URL has no scheme."""
    if _SCHEME_RE.match(url or ""):
        return url
    return "https://" + url


def parse_url(url: str | None) -> urlparse:
    """Parse a URL, tolerating a missing scheme (treated as https)."""
    url = ensure_scheme(url or "")
    return urlparse(url)


def get_hostname(url: str | None) -> str:
    """The lowercased hostname of a URL, or ''."""
    parsed = parse_url(url)
    return (parsed.hostname or "").lower()


def get_origin(url: str | None) -> str:
    """scheme://netloc for a URL, lowercasing scheme and host."""
    parsed = parse_url(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = f"{host}:{port}" if port else host
    return f"{scheme}://{netloc}"


def is_http_url(url: str) -> bool:
    """True for http(s) URLs."""
    return parse_url(url).scheme in {"http", "https"}


def same_domain(url_a: str, url_b: str) -> bool:
    """True when two URLs share the same hostname."""
    return get_hostname(url_a) == get_hostname(url_b)


def canonicalize(url: str) -> str:
    """Normalized form: https, lowercase host, lowercase path, no trailing slash.

    Used for de-duplicating seeds and crawled URLs where sites treat
    /About and /about as the same page.
    """
    parsed = parse_url(url)
    path = parsed.path.rstrip("/").lower() or "/"
    netloc = parsed.hostname.lower() if parsed.hostname else ""
    return urlunparse(("https", netloc, path, "", "", ""))


def seed_key(url: str) -> str:
    """A comparison key for de-duplicating seed URLs (host + canonical path)."""
    return canonicalize(url)


def get_path_segments(url: str) -> list[str]:
    """The non-empty path segments of a URL, lowercased."""
    parsed = parse_url(url)
    return [seg.lower() for seg in parsed.path.split("/") if seg]


def query_params(url: str) -> dict[str, str]:
    """Query string parameters as a dict (first value wins)."""
    parsed = parse_url(url)
    return dict(parse_qsl(parsed.query))


def join_url(base: str, path: str) -> str:
    """Resolve a (possibly relative) path against a base URL."""
    return urljoin(ensure_scheme(base), path)


def config_filename(website_url: str | None) -> str:
    """The safe filename for a config, or 'default.json'.

    Ported from the Flask writer: lowercase host only, `www` preserved, non-host
    characters flattened to underscores so it can never traverse directories.
    """
    host = get_hostname(website_url)
    safe = re.sub(r"[^a-z0-9.-]", "_", host) or "default"
    return f"{safe}.json"