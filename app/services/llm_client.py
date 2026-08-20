"""Thin LLM client wrapping Google Generative AI (spec section 2.4).

The service talks to Gemini directly with its own GENAI_API_KEY; it does not
proxy through any upstream wrapper. Kept in one module so nothing else imports
the SDK.
"""

from __future__ import annotations

import logging

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def _client(model: str = ""):
    from google import genai

    settings = get_settings()
    if not settings.genai_api_key:
        raise RuntimeError("GENAI_API_KEY is not set")
    genai_client = genai.Client(api_key=settings.genai_api_key)
    return genai_client, model or settings.gemini_model


def llm_complete(prompt: str, *, json_mode: bool = False) -> str | None:
    """Run a single prompt and return the raw text response (or None).

    `json_mode=True` asks Gemini for a JSON response (spec sections 4.4 and 4.6
    both rely on structured/selector-only answers). A missing/invalid API key is
    not fatal: it returns None so callers can degrade to baseline configs.
    """
    settings = get_settings()
    try:
        client, model = _client()
    except RuntimeError as exc:
        logger.warning("LLM unavailable: %s", exc)
        return None

    attempts = max(1, int(settings.llm_retry))
    config = None
    if json_mode:
        # google-genai uses pydantic-style config; a plain dict works for the
        # simple mime-type switch used here.
        config = {"response_mime_type": "application/json"}

    for attempt in range(attempts):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            text = (response.text or "").strip()
            if text:
                return text
            logger.warning("LLM returned empty response (attempt %s/%s)", attempt + 1, attempts)
        except Exception:
            logger.exception("LLM call failed (attempt %s/%s)", attempt + 1, attempts)
            if attempt == attempts - 1:
                return None
    return None