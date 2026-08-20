"""Orchestration service.

Runs the full data flow from the spec (section 2.3): discovery -> rendering ->
analysis -> LLM compile -> compose -> validate -> persist. The route layer stays
thin; every pipeline step lives here so it can be reused and tested directly.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import defaults as d
from app.config.settings import Settings, get_settings
from app.services import content_guard, persistence
from app.services.analyzer import SelectorAnalyzer
from app.services.async_util import run_async
from app.services.discovery import SiteDiscovery
from app.services.exceptions import ConfigError
from app.services.llm_compiler import LLMCompiler
from app.services.renderer import PageRenderer
from app.services.validator import ConfigValidator
from app.utils import platform_detection, safety_guards, url_normalizer as nu

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# config composition
# --------------------------------------------------------------------------- #
def _heuristic_list_dirs(page_urls: list[str]) -> list[str]:
    """Directories like /tag/ or /category/ to skip, surfaced from the URLs."""
    found: set[str] = set()
    for url in page_urls:
        for segment in nu.get_path_segments(url):
            if segment in d.LIST_PATH_SEGMENTS and segment not in found:
                found.add(segment)
    return sorted(f"/{key}" for key in found)


def compose_config(
    url: str,
    *,
    discovered_urls: list[str],
    seeds: list[str],
    platforms: list[str],
    llm_payload: dict[str, list[str]],
    limit: int | None = None,
) -> dict[str, Any]:
    """Build the full config dict from the pipeline outputs.

    Starts from the shared baselines and adds, in order: heuristic list dirs,
    deterministic platform selectors, then guarded LLM selectors. `limit` is
    applied only when explicitly provided (None = full crawl).
    """
    origin = nu.get_origin(url)
    host = nu.get_hostname(url)

    paths_to_skip = list(d.BASELINE_PATHS_TO_SKIP)
    for extra in _heuristic_list_dirs(discovered_urls):
        if extra not in paths_to_skip:
            paths_to_skip.append(extra)
    for extra in llm_payload.get("pathsToSkip") or []:
        if extra not in paths_to_skip:
            paths_to_skip.append(extra)

    elements = list(d.BASELINE_ELEMENTS_TO_REMOVE)
    seen = set(elements)

    # Option B: known-platform boilerplate, applied deterministically.
    table = platform_detection.platform_elements_to_remove()
    for platform in platforms:
        for selector in table.get(platform, []):
            if selector not in seen and safety_guards.is_safe_selector(selector):
                seen.add(selector)
                elements.append(selector)

    # Option A: LLM refined per-site boilerplate, guarded and capped.
    for selector in safety_guards.filter_safe_selectors(
        llm_payload.get("elementsToRemove") or [], exclude=seen
    ):
        if selector not in seen:
            seen.add(selector)
            elements.append(selector)

    config = {
        "websiteUrl": origin,
        "seedUrls": seeds,
        "pathsToSkip": paths_to_skip,
        "scrapeWithGemini": False,
        "limit": limit,
        "puppeteerOnly": True,
        "requestsPerMinute": 500,
        "elementsToRemove": elements,
        "geminiModel": get_settings().gemini_model,
        "confidenceScore": 0.0,
        "metadata": {},
    }
    config.update(d.STRIP_FLAGS)
    return config


# --------------------------------------------------------------------------- #
# confidence
# --------------------------------------------------------------------------- #
def compute_confidence(platforms: list[str], validation_score: float) -> tuple[float, str]:
    """A simple confidence score + label from signal strength.

    Platform detection and validation both contribute; anything below the
    threshold rounds the label down so low-quality configs are visibly flagged.
    """
    base = 0.5
    if platforms:
        base += 0.1 * min(3, len(platforms))
    score = round(min(1.0, base * 0.4 + validation_score * 0.6), 2)
    label = "high" if score >= 0.8 else ("medium" if score >= 0.6 else "low")
    return score, label


# --------------------------------------------------------------------------- #
# the pipeline
# --------------------------------------------------------------------------- #
def generate(
    url: str,
    *,
    persist: bool = False,
    sample_pages: int | None = None,
    ai_refine: bool = True,
    limit: int | None = None,
    config_dir: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Generate (and optionally persist) a config for a website (spec section 2.3).

    Returns {host, filename, path?, config, validation}. Raises ConfigError for
    unreachable sites and ValidationFailed when a persisted config fails checks.
    """
    settings = settings or get_settings()
    address = nu.ensure_scheme(url)
    origin = nu.get_origin(address)
    host = nu.get_hostname(address)
    if not host:
        raise ConfigError(f"Not a usable website address: {url!r}")

    # 1. discovery
    discovery = SiteDiscovery(origin, settings)
    target = sample_pages or settings.default_sample_pages
    discovered = discovery.get_diverse_urls(n=target)
    if not discovered:
        raise ConfigError(f"Could not discover any pages on {host}.")

    # 2. rendering
    renderer = PageRenderer(settings=settings)
    validator = ConfigValidator(settings=settings)
    try:
        rendered = run_async(renderer.render_batch(discovered))
        rendered = [r for r in rendered if r.get("html")]
        if not rendered:
            raise ConfigError(f"Could not render any page on {host}.")

        # 3. analysis
        analyzer = SelectorAnalyzer()
        inventory = analyzer.aggregate_inventory(rendered, settings)
        platforms = analyzer.detect_platforms(rendered)
        json_ld = analyzer.extract_json_ld(rendered)
        num_pages = len(rendered)
        first_html = rendered[0].get("html") or ""

        # 4. LLM compile
        compiler = LLMCompiler()
        llm_payload = compiler.compile_config(
            url=host,
            platforms=platforms,
            inventory=inventory,
            json_ld_blobs=json_ld,
            num_pages=num_pages,
            sample_html=first_html,
        )

        # 5. compose
        seeds = _compose_seeds(origin, discovered)
        config = compose_config(
            origin,
            discovered_urls=discovered,
            seeds=seeds,
            platforms=platforms,
            llm_payload=llm_payload,
            limit=limit,
        )

        # 5b. content guard: enforce "never remove the content" on the rendered
        # DOM, dropping / narrowing any selector that would strip a page's text.
        # This is the mechanism that generalizes to arbitrary site layouts.
        guard = content_guard.prune_elements(
            [r.get("html") or "" for r in rendered if r.get("html")],
            config["elementsToRemove"],
        )
        config["elementsToRemove"] = guard["kept"]
        warnings = []
        for d in guard["dropped"]:
            entry = {"selector": d["selector"], "reason": d["reason"]}
            if d.get("kept"):
                entry["kept"] = d["kept"]
            warnings.append(entry)

        # 6. validate
        test_urls = [page["url"] for page in rendered][: settings.validation_max_pages]
        validation = run_async(validator.validate_config(config, test_urls))
    finally:
        # release the browser(s) so the shared event loop shuts down cleanly
        run_async(renderer.close())
        run_async(validator.close())

    # 7. confidence + result
    confidence, label = compute_confidence(platforms, validation["validation_score"])
    degraded = not validation["passed"]

    result: dict[str, Any] = {
        "host": host,
        "config": config,
        "validation": validation,
        "confidence": confidence,
        "confidence_label": label,
        "platforms": platforms,
        "degraded": degraded,
        "warnings": warnings,
        "pruned": guard["counts"],
    }

    # Best-effort: write the content-safe config even when validation degrades,
    # and report why. A hard failure is reserved for sites we cannot render.
    if persist:
        written = persistence.write_config(
            config,
            config_dir=config_dir,
            platforms=platforms,
            confidence=confidence,
            confidence_label=label,
            validation_score=validation["validation_score"],
        )
        result.update(written)

    # keep the returned config in sync with the persisted form even when
    # persist=False so the response matches the spec's config schema
    config["confidenceScore"] = confidence
    config["metadata"] = persistence._metadata(
        platforms=platforms,
        confidence=confidence,
        confidence_label=label,
        validation_score=validation["validation_score"],
    )

    logger.info(
        "Generated scraper config",
        extra={"host": host, "pages": num_pages, "platforms": platforms,
               "validation_score": validation["validation_score"]},
    )
    return result


def _compose_seeds(origin: str, discovered: list[str]) -> list[str]:
    """Seeds = homepage first, then diverse pages, deduped and capped."""
    seeds: list[str] = [origin]
    seen = {nu.seed_key(origin)}
    for candidate in discovered:
        key = nu.seed_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(candidate)
        if len(seeds) >= get_settings().max_seeds:
            break
    return seeds