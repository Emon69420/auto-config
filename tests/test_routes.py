"""Route-level (e2e) tests for the Flask API using the test client.

The generator/validator/healer services are mocked so these tests assert the
HTTP contract (auth, validation, status codes) without a browser or network.
"""

import json

from app.services import generator_service


def _ok_result():
    return {
        "host": "example.com",
        "filename": "example.com.json",
        "config": {
            "websiteUrl": "https://example.com",
            "seedUrls": ["https://example.com"],
            "pathsToSkip": ["/admin"],
            "elementsToRemove": ["nav"],
            "puppeteerOnly": True,
            "confidenceScore": 0.9,
            "metadata": {"platform_detected": ["custom"], "confidence": "high"},
        },
        "validation": {"passed": True, "validation_score": 0.95, "details": []},
    }


def test_generate_requires_api_key(client):
    resp = client.post("/generate", json={"url": "https://example.com"})
    assert resp.status_code == 401


def test_generate_success(client, auth_headers, monkeypatch):
    monkeypatch.setattr(generator_service, "generate", lambda *a, **kw: _ok_result())
    resp = client.post("/generate", json={"url": "https://example.com", "persist": False},
                       headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["host"] == "example.com"
    assert data["config"]["puppeteerOnly"] is True


def test_generate_rejects_invalid_payload(client, auth_headers):
    resp = client.post("/generate", json={"url": "not a url"}, headers=auth_headers)
    assert resp.status_code == 400


def test_generate_maps_config_error(client, auth_headers, monkeypatch):
    from app.services.exceptions import ConfigError

    def boom(*a, **kw):
        raise ConfigError("Site unreachable")

    monkeypatch.setattr(generator_service, "generate", boom)
    resp = client.post("/generate", json={"url": "https://example.com"}, headers=auth_headers)
    assert resp.status_code == 400
    assert "Site unreachable" in resp.get_json()["error"]


def test_validate_requires_api_key(client):
    resp = client.post("/validate", json={})
    assert resp.status_code == 401


def test_validate_accepts_config(client, auth_headers, monkeypatch):
    from app.services.validator import ConfigValidator

    async def fake_validate(self, config, test_urls):
        return {"passed": True, "validation_score": 0.9, "details": []}

    monkeypatch.setattr(ConfigValidator, "validate_config", fake_validate)
    body = {
        "config": {"websiteUrl": "https://example.com", "seedUrls": ["https://example.com"]},
        "test_urls": ["https://example.com"],
    }
    resp = client.post("/validate", json=body, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["passed"] is True


def test_heal_requires_api_key(client):
    resp = client.post("/heal", json={})
    assert resp.status_code == 401


def test_heal_returns_result(client, auth_headers, monkeypatch):
    from app.services.auto_healer import AutoHealer

    async def fake_heal(self, url, broken, field):
        return {"old": broken, "new": ".new-nav", "success": True}

    monkeypatch.setattr(AutoHealer, "heal_broken_selector", fake_heal)
    body = {"url": "https://example.com", "broken_selector": ".old", "field_name": "elementsToRemove"}
    resp = client.post("/heal", json=body, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] in ("healthy", "degraded")