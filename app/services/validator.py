"""Validation service (spec section 4.5) - ConfigValidator.

Proves a config works before it is saved: renders sample pages, counts matched
boilerplate before and after removal, and checks that main content survives
(>500 chars) while a meaningful reduction happened (>10%). A config passes when
its per-page success rate clears the threshold (default >= 0.8), and the caller
(persistence) refuses to save failing configs (spec section 3.1).
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright

from app.config.settings import Settings, get_settings
from app.services.renderer import goto_resilient

logger = logging.getLogger(__name__)

_MAIN_SELECTOR = "main, .main-content, #content, body"
_COUNT_EVAL = """(selectors) => {
    let count = 0;
    selectors.forEach((sel) => {
        try { count += document.querySelectorAll(sel).length; } catch (e) {}
    });
    return count;
}"""
_REMOVE_EVAL = """(selectors) => {
    selectors.forEach((sel) => {
        try {
            document.querySelectorAll(sel).forEach((el) => el.remove());
        } catch (e) {}
    });
}"""
_MAIN_LENGTH_EVAL = """() => {
    const main = document.querySelector('main')
        || document.querySelector('.main-content')
        || document.querySelector('#content')
        || document.body;
    return main.textContent.trim().length;
}"""


class ConfigValidator:
    """Measures whether a config's elementsToRemove work on real pages."""

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self.settings = settings
        self.threshold = settings.validation_threshold
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def close(self):
        for closer in (self._browser, self._playwright):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    logger.exception("Error closing validator resources")
        self._browser = None
        self._playwright = None

    async def _measure_url(self, url: str, selectors: list[str]) -> dict:
        """Measure reduction and content preservation for one URL."""
        browser = await self._ensure_browser()
        page = None
        try:
            page = await browser.new_page()
            await goto_resilient(page, url, self.settings.render_timeout_ms)
            before = await page.evaluate(_COUNT_EVAL, selectors)
            await page.evaluate(_REMOVE_EVAL, selectors)
            after = await page.evaluate(_COUNT_EVAL, selectors)
            content_length = await page.evaluate(_MAIN_LENGTH_EVAL)

            reduction = ((before - after) / before * 100) if before else 0.0
            passed = reduction > 10 and int(content_length or 0) > 500
            return {
                "url": url,
                "reduction_pct": round(reduction, 2),
                "main_content_length": int(content_length or 0),
                "passed": bool(passed),
            }
        except Exception as exc:
            logger.warning("Validation render failed for %s: %s", url, exc)
            return {
                "url": url,
                "reduction_pct": 0.0,
                "main_content_length": 0,
                "passed": False,
            }
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    async def validate_config(self, config: dict, test_urls: list[str]) -> dict:
        """Validate a config against sample pages (spec section 4.5).

        Returns {passed, validation_score, details}.
        """
        selectors = config.get("elementsToRemove") or []
        test_urls = [u for u in test_urls if u]
        if not test_urls:
            return {"passed": False, "validation_score": 0.0, "details": []}

        details = []
        for url in test_urls:
            details.append(await self._measure_url(url, selectors))

        passed_count = sum(1 for d in details if d["passed"])
        score = passed_count / len(details) if details else 0.0
        return {
            "passed": bool(score >= self.threshold),
            "validation_score": round(score, 3),
            "details": details,
        }