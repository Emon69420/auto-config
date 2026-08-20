"""Unit tests for the validator's aggregation logic (with a fake measurer)."""

import pytest

from app.services.validator import ConfigValidator


@pytest.mark.asyncio
async def test_validate_config_pass_threshold():
    validator = ConfigValidator()

    async def fake_measure(url, selectors):
        return {"url": url, "reduction_pct": 45.0, "main_content_length": 5000, "passed": True}

    validator._measure_url = fake_measure
    report = await validator.validate_config({"elementsToRemove": ["nav"]},
                                             ["https://a.com/1", "https://a.com/2"])
    assert report["passed"] is True
    assert report["validation_score"] == 1.0
    assert len(report["details"]) == 2


@pytest.mark.asyncio
async def test_validate_config_fails_below_threshold():
    validator = ConfigValidator()

    results = iter([
        {"url": "1", "reduction_pct": 45.0, "main_content_length": 5000, "passed": True},
        {"url": "2", "reduction_pct": 0.0, "main_content_length": 0, "passed": False},
    ])

    async def fake_measure(url, selectors):
        return next(results)

    validator._measure_url = fake_measure
    report = await validator.validate_config({"elementsToRemove": ["nav"]},
                                             ["1", "2"])
    assert report["passed"] is False
    assert report["validation_score"] == 0.5


@pytest.mark.asyncio
async def test_validate_config_empty_urls_fails_open():
    validator = ConfigValidator()
    report = await validator.validate_config({"elementsToRemove": ["nav"]}, [])
    assert report["passed"] is False
    assert report["details"] == []