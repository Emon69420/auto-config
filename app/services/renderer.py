"""Rendering service (spec section 4.2) - PageRenderer.

Renders pages in headless Chromium with JavaScript enabled, so analysis runs
against the real DOM (fixing the raw-HTML blind spot on JS-rendered sites like
Shopify). Extracts rendered HTML, JSON-LD, and OpenGraph tags per page.
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import async_playwright

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_JSON_LD_EVAL = """() => {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    return Array.from(scripts).map((s) => {
        try {
            return JSON.parse(s.textContent);
        } catch (err) {
            return null;
        }
    }).filter(Boolean);
}"""

_OG_TAGS_EVAL = """() => {
    const tags = {};
    document.querySelectorAll('meta[property]').forEach((m) => {
        const key = m.getAttribute('property');
        if (!tags[key]) tags[key] = m.getAttribute('content');
    });
    return tags;
}"""


async def goto_resilient(page, url: str, timeout_ms: int):
    """Navigate a page, tolerating sites that never let the network idle.

    Tries `networkidle` first (spec section 4.2), then falls back to `load` and
    a short settle delay so chat widgets / analytics don't cause timeouts that
    silently drop otherwise-renderable pages.
    """
    try:
        await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        return
    except Exception:
        pass
    try:
        await page.goto(url, wait_until="load", timeout=timeout_ms)
    except Exception:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    await page.wait_for_timeout(2000)


class PageRenderer:
    """Renders pages and extracts DOM signals needed by the analyzer."""

    def __init__(
        self,
        *,
        concurrency: int | None = None,
        timeout_ms: int | None = None,
        settings: Settings | None = None,
    ):
        settings = settings or get_settings()
        self.settings = settings
        self.concurrency = concurrency or settings.render_concurrency
        self.timeout_ms = timeout_ms or settings.render_timeout_ms
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def close(self):
        """Close the browser and playwright driver (call in teardown)."""
        for closer in (self._browser, self._playwright):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    logger.exception("Error closing renderer resources")
        self._browser = None
        self._playwright = None

    async def render_page(self, url: str) -> dict:
        """Render a single page and extract HTML, JSON-LD, and OG tags.

        Tries the strict `networkidle` wait first (spec section 4.2), but falls
        back to `load` + a short settle delay when a site's chat widget or
        analytics never lets the network idle -- otherwise a perfectly good page
        would time out and count as unrendered.
        """
        browser = await self._ensure_browser()
        page = None
        try:
            page = await browser.new_page()
            await goto_resilient(page, url, self.timeout_ms)
            html = await page.content()
            json_ld = await page.evaluate(_JSON_LD_EVAL)
            og_tags = await page.evaluate(_OG_TAGS_EVAL)
            return {"url": url, "html": html, "json_ld": json_ld, "og_tags": og_tags}
        except Exception as exc:
            logger.warning("Rendering failed for %s: %s", url, exc)
            return {"url": url, "html": "", "json_ld": [], "og_tags": {}, "error": str(exc)}
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    async def render_batch(self, urls: list[str]) -> list[dict]:
        """Render many pages, limited by a concurrency semaphore."""
        semaphore = asyncio.Semaphore(self.concurrency)

        async def one(url: str) -> dict:
            async with semaphore:
                return await self.render_page(url)

        return await asyncio.gather(*(one(url) for url in urls))