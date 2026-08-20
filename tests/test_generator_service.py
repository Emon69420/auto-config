"""Unit tests for the full generate orchestration (all external calls mocked)."""

import json

from app.services import generator_service
from app.services.async_util import close_loop


def _fake_render_batch(urls):
    async def _inner(self, urls):
        return [
            {
                "url": u,
                "html": "<html><div id='shopify-section-h' class='nav'>x</div><footer>f</footer></html>",
                "json_ld": [{"@type": "Organization"}],
                "og_tags": {},
            }
            for u in urls
        ]
    return _inner


def _fake_validate():
    async def _inner(self, config, test_urls):
        return {"passed": True, "validation_score": 1.0, "details": []}
    return _inner


def test_generate_pipeline_persists_config(monkeypatch, settings, tmp_path):
    monkeypatch.setattr(
        "app.services.discovery.SiteDiscovery.get_diverse_urls",
        lambda self, n=None: ["https://example.com", "https://example.com/about"],
    )
    monkeypatch.setattr("app.services.renderer.PageRenderer.render_batch", _fake_render_batch("fake"))
    monkeypatch.setattr(
        "app.services.validator.ConfigValidator.validate_config", _fake_validate()
    )
    monkeypatch.setattr(
        "app.services.llm_client.llm_complete",
        lambda prompt, json_mode=False: json.dumps({"elementsToRemove": [".nav"], "pathsToSkip": []}),
    )

    config_dir = str(tmp_path / "out" / "configs")
    import pathlib
    pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)

    result = generator_service.generate(
        "https://example.com",
        persist=True,
        sample_pages=3,
        config_dir=config_dir,
        settings=settings,
    )
    close_loop()

    assert result["host"] == "example.com"
    assert result["filename"] == "example.com.json"
    assert result["validation"]["passed"] is True
    assert result["config"]["puppeteerOnly"] is True
    assert result["config"]["metadata"]["platform_detected"] == ["shopify"]

    written = (config_dir + "/example.com.json")
    import os
    assert os.path.exists(written)


def test_generate_raises_on_unreachable_host(settings):
    import pytest
    from app.services.exceptions import ConfigError
    with pytest.raises(ConfigError):
        generator_service.generate("not a url", settings=settings)


def test_generate_persists_pruned_config_when_validation_degrades(monkeypatch, settings, tmp_path):
    """Validation may degrade below threshold, but the content-safe config is still
    written (best-effort) with a flag, instead of a hard 400/raise."""

    async def failing_validate(self, config, test_urls):
        return {"passed": False, "validation_score": 0.4, "details": []}

    monkeypatch.setattr(
        "app.services.discovery.SiteDiscovery.get_diverse_urls",
        lambda self, n=None: ["https://example.com/a"],
    )
    monkeypatch.setattr("app.services.renderer.PageRenderer.render_batch", _fake_render_batch("fake"))
    monkeypatch.setattr(
        "app.services.validator.ConfigValidator.validate_config", failing_validate
    )
    monkeypatch.setattr(
        "app.services.llm_client.llm_complete",
        lambda prompt, json_mode=False: "{}",
    )

    config_dir = str(tmp_path / "out" / "configs")
    import pathlib
    pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)

    result = generator_service.generate(
        "https://example.com", persist=True, settings=settings, config_dir=config_dir
    )
    close_loop()

    assert result["degraded"] is True
    assert result["validation"]["passed"] is False
    import os
    assert os.path.exists(config_dir + "/example.com.json")