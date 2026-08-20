"""Auto-healer service (spec section 4.6) - AutoHealer.

Repairs a broken selector: renders the live page, shows its current DOM to the
LLM, asks for a replacement selector, then verifies the replacement actually
matches nodes before accepting it. Returns the original selector when it cannot
improve on it.
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright

from app.config.prompts import build_heal_prompt
from app.config.settings import Settings, get_settings
from app.services import llm_client
from app.services.renderer import goto_resilient
from app.utils import safety_guards

logger = logging.getLogger(__name__)


class AutoHealer:
    """Repairs a selector that no longer matches the live DOM."""

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self.settings = settings
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
                    logger.exception("Error closing healer resources")
        self._browser = None
        self._playwright = None

    async def heal_broken_selector(
        self,
        url: str,
        broken_selector: str,
        field_name: str,
    ) -> dict:
        """Return {old, new, success} for a broken selector (spec section 4.6)."""
        browser = await self._ensure_browser()
        page = None
        try:
            page = await browser.new_page()
            await goto_resilient(page, url, self.settings.render_timeout_ms)

            snapshot = await page.evaluate("document.documentElement.outerHTML")
            snapshot = (snapshot or "")[: self.settings.max_heal_snapshot_chars]

            prompt = build_heal_prompt(broken_selector, field_name, snapshot)
            proposed = llm_client.llm_complete(prompt, json_mode=False)
            new_selector = (proposed or "").strip().strip("`").strip()

            if not new_selector or not safety_guards.is_safe_selector(new_selector):
                logger.warning("Healer rejected proposed selector %r", new_selector)
                return {"old": broken_selector, "new": broken_selector, "success": False}

            matches = await page.query_selector_all(new_selector)
            if matches:
                return {"old": broken_selector, "new": new_selector, "success": True}

            logger.warning("Healer proposed selector matched nothing: %r", new_selector)
            return {"old": broken_selector, "new": broken_selector, "success": False}
        except Exception as exc:
            logger.warning("Heal failed for %s: %s", url, exc)
            return {"old": broken_selector, "new": broken_selector, "success": False}
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass