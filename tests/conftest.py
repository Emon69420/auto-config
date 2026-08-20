"""Shared pytest fixtures.

The service is configured from the environment via get_settings(); tests build
their own Settings instances and inject them explicitly rather than mutating
globals, so tests stay order-independent.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings


@pytest.fixture
def settings(tmp_path):
    """A Settings instance pointing config output at a temp dir."""
    return Settings(
        genai_api_key="test-key",
        internal_api_key="test-key",
        config_dir=str(tmp_path / "configs"),
        default_sample_pages=3,
        max_sample_pages=20,
        validation_min_pages=1,
        validation_max_pages=3,
        render_concurrency=2,
    )


@pytest.fixture
def app(settings):
    from app.main import create_app

    application = create_app(settings)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"x-api-key": "test-key", "Content-Type": "application/json"}