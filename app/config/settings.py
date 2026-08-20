"""Environment-driven settings for the scraper-config-generator service.

Every tunable is read from the environment (see .env.example and
docker-compose.yml). Keeping them all in one module means the rest of the
codebase imports one place and never touches os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

DEFAULT_STRIP_FLAGS = {
    "stripImages": True,
    "stripScripts": True,
    "stripStyles": True,
    "stripLinks": True,
    "stripMeta": True,
    "stripHead": True,
    "stripNoscript": True,
    "stripSvg": True,
}


def _env(name: str, default=None):
    """Read an environment variable, trimming whitespace, with a default."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value != "" else default


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to a default."""
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable, falling back to a default."""
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """All service configuration. Frozen so it can be shared safely."""

    # --- credentials ---
    genai_api_key: str = ""
    internal_api_key: str = ""

    # --- paths ---
    config_dir: str = "./configs"
    playwright_browsers_path: str = ""

    # --- generation defaults (spec section 9.2) ---
    default_sample_pages: int = 10
    max_sample_pages: int = 20
    default_ai_refine: bool = True
    default_limit: int = 5
    gemini_model: str = "gemini-2.5-flash"

    # --- rendering (spec 4.2) ---
    render_concurrency: int = 3
    render_timeout_ms: int = 30000

    # --- analysis (spec 4.3) ---
    inventory_top_ids: int = 50
    inventory_top_classes: int = 100
    inventory_top_tags: int = 20

    # --- LLM compiler (spec 4.4) ---
    max_ai_selectors: int = 15
    html_fragment_chars: int = 2500
    llm_retry: int = 1

    # --- validation (spec 4.5) ---
    validation_threshold: float = 0.8
    validation_min_pages: int = 3
    validation_max_pages: int = 5

    # --- auto-heal (spec 4.6) ---
    max_heal_snapshot_chars: int = 5000

    # --- discovery (spec 4.1) ---
    fetch_timeout: int = 30
    fallback_crawl_max: int = 20
    diverse_urls_target: int = 10
    max_seeds: int = 10
    max_pages_per_sitemap: int = 200

    # --- api (spec 9.3) ---
    rate_limit: str = "10 per minute"

    # --- observability (spec 8) ---
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            genai_api_key=_env("GENAI_API_KEY", ""),
            internal_api_key=_env("FLASK_INTERNAL_API_KEY", ""),
            config_dir=_env("SCRAPER_CONFIG_DIR", "./configs"),
            playwright_browsers_path=_env("PLAYWRIGHT_BROWSERS_PATH", ""),
            default_sample_pages=_env_int("DEFAULT_SAMPLE_PAGES", 10),
            max_sample_pages=_env_int("MAX_SAMPLE_PAGES", 20),
            default_ai_refine=_env_bool("DEFAULT_AI_REFINE", True),
            default_limit=_env_int("DEFAULT_LIMIT", 5),
            gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
            render_concurrency=_env_int("RENDER_CONCURRENCY", 3),
            render_timeout_ms=_env_int("RENDER_TIMEOUT_MS", 30000),
            inventory_top_ids=_env_int("INVENTORY_TOP_IDS", 50),
            inventory_top_classes=_env_int("INVENTORY_TOP_CLASSES", 100),
            inventory_top_tags=_env_int("INVENTORY_TOP_TAGS", 20),
            max_ai_selectors=_env_int("MAX_AI_SELECTORS", 15),
            html_fragment_chars=_env_int("HTML_FRAGMENT_CHARS", 2500),
            llm_retry=_env_int("LLM_RETRY", 1),
            validation_threshold=float(_env("VALIDATION_THRESHOLD", "0.8")),
            validation_min_pages=_env_int("VALIDATION_MIN_PAGES", 3),
            validation_max_pages=_env_int("VALIDATION_MAX_PAGES", 5),
            max_heal_snapshot_chars=_env_int("MAX_HEAL_SNAPSHOT_CHARS", 5000),
            fetch_timeout=_env_int("FETCH_TIMEOUT", 30),
            fallback_crawl_max=_env_int("FALLBACK_CRAWL_MAX", 20),
            diverse_urls_target=_env_int("DIVERSE_URLS_TARGET", 10),
            max_seeds=_env_int("MAX_SEEDS", 10),
            max_pages_per_sitemap=_env_int("MAX_PAGES_PER_SITEMAP", 200),
            rate_limit=_env("RATE_LIMIT", "10 per minute"),
            log_level=_env("LOG_LEVEL", "INFO"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings for the process."""
    return Settings.from_env()