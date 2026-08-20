"""Discovery service (spec section 4.1) - SiteDiscovery.

Finds the pages of a website before it is rendered: robots.txt, sitemaps
(XML, indexes, .gz), and a BFS crawl fallback when no sitemap exists. Output is a
diverse set of URLs (homepage + product + blog + assorted) for sampling.
"""

from __future__ import annotations

import gzip
import random
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from lxml import etree

from app.config.settings import Settings, get_settings
from app.utils import url_normalizer as nu
from app.utils.url_normalizer import canonicalize, get_origin, is_http_url, same_domain

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class SiteDiscovery:
    """Discovers the pages of a single site."""

    def __init__(self, base_url: str, settings: Settings | None = None):
        settings = settings or get_settings()
        self.settings = settings
        self.base_url = nu.ensure_scheme(base_url or "")
        self.origin = get_origin(self.base_url)
        self.host = nu.get_hostname(self.base_url)
        self.timeout = settings.fetch_timeout

    # ------------------------------------------------------------------ #
    # low-level fetching
    # ------------------------------------------------------------------ #
    def _get(self, url: str) -> str:
        """Fetch a URL and return its body text, or '' on any failure."""
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout,
            )
            response.raise_for_status()
            if url.endswith(".gz"):
                return gzip.decompress(response.content).decode("utf-8", "ignore")
            return response.text
        except Exception:
            return ""

    def fetch_robots(self) -> list[str]:
        """Sitemap URLs advertised in robots.txt (spec 4.1)."""
        body = self._get(urljoin(self.origin, "/robots.txt"))
        if not body:
            return []
        return [line.split(":", 1)[1].strip() for line in body.splitlines()
                if line.lower().lstrip().startswith("sitemap:")]

    # ------------------------------------------------------------------ #
    # sitemap parsing (handles XML, indexes, and .gz)
    # ------------------------------------------------------------------ #
    def fetch_sitemaps(self) -> list[str]:
        """All page URLs found in the site's sitemap(s)."""
        candidates = list(self.fetch_robots())
        for guess in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
            candidate = urljoin(self.origin, guess)
            if candidate not in candidates:
                candidates.append(candidate)

        pages: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            for url in self._flatten_sitemap(candidate, depth=0, seen=seen):
                if url not in pages and len(pages) < self.settings.max_pages_per_sitemap:
                    pages.append(url)
        return pages

    def _flatten_sitemap(self, sitemap_url: str, depth: int, seen: set[str]) -> list[str]:
        """Recursively flatten a sitemap (or sitemap index) into page URLs."""
        if depth > 3:
            return []
        if sitemap_url in seen:
            return []
        seen.add(sitemap_url)

        body = self._get(sitemap_url)
        if not body:
            return []
        try:
            root = etree.fromstring(body.encode("utf-8"))
        except etree.XMLSyntaxError:
            return []

        results: list[str] = []
        for loc in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
            value = (loc.text or "").strip()
            if not value:
                continue
            # A <loc> pointing at another sitemap (index) is recursed;
            # otherwise it is a page.
            sitemap_index_hint = any(
                marker in value.lower()
                for marker in (".xml", ".xml.gz", "sitemap", "index")
            )
            if sitemap_index_hint and value != sitemap_url:
                results.extend(
                    self._flatten_sitemap(value, depth + 1, seen)
                )
            else:
                results.append(value)
        return results

    # ------------------------------------------------------------------ #
    # BFS crawl fallback (spec 4.1)
    # ------------------------------------------------------------------ #
    def fallback_crawl(self, n: int = 20) -> list[str]:
        """Crawl from the homepage when the site has no sitemap."""
        queue: list[str] = [self.base_url]
        found: list[str] = []
        seen: set[str] = set()

        while queue and len(found) < n:
            current = queue.pop(0)
            key = canonicalize(current)
            if key in seen:
                continue
            seen.add(key)

            body = self._get(current)
            if body:
                found.append(current)
                if len(found) >= n:
                    break
                for link in self._extract_links(body):
                    if is_http_url(link) and same_domain(link, self.base_url):
                        queue.append(link)
        return found

    def _extract_links(self, html: str) -> list[str]:
        """Absolute http(s) hrefs on the same site, deduplicated."""
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return []
        links = {urljoin(self.base_url, a.get("href", "")) for a in soup.find_all("a")}
        return sorted(l for l in links if is_http_url(l))

    # ------------------------------------------------------------------ #
    # diverse URL selection (spec 4.1)
    # ------------------------------------------------------------------ #
    def get_diverse_urls(self, n: int | None = None) -> list[str]:
        """A diverse set of URLs for sampling: homepage + products + blog + fill."""
        n = n or self.settings.diverse_urls_target
        all_urls = self.fetch_sitemaps()
        if not all_urls:
            all_urls = self.fallback_crawl(max(n, self.settings.fallback_crawl_max))

        diverse: list[str] = [self.base_url]
        page_types = {
            "product": [u for u in all_urls if "/products/" in u.lower()],
            "collection": [u for u in all_urls if "/collections/" in u.lower()],
            "blog": [u for u in all_urls if "/blog" in u.lower() or "/blogs/" in u.lower()],
        }
        for type_urls in page_types.values():
            if type_urls and len(diverse) < n:
                chosen = next((u for u in type_urls if u not in diverse), None)
                if chosen:
                    diverse.append(chosen)

        remaining = [u for u in all_urls if u not in diverse]
        pool = random.sample(remaining, min(n - len(diverse), len(remaining))) if remaining else []
        diverse.extend(pool)
        return [u for u in diverse if u][:n]