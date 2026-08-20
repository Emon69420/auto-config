"""Shared authorization for internal routes (spec section 9.1).

The service is meant for trusted callers; every mutating route reads
x-api-key and compares it against FLASK_INTERNAL_API_KEY. When the key is not
configured the route fails closed (401) rather than opening the service up.
"""

from __future__ import annotations

from functools import wraps

from flask import current_app, jsonify, request


def set_settings(app, app_settings):
    """Attach the service Settings to a Flask app."""
    app.config["SETTINGS"] = app_settings


def get_current_settings():
    """The Settings instance for the active request's app."""
    return current_app.config.get("SETTINGS")


def require_api_key(view):
    """Decorator rejecting requests without the right x-api-key header."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        settings = get_current_settings()
        expected = settings.internal_api_key if settings else ""
        sent = request.headers.get("x-api-key", "")
        if not expected or sent != expected:
            return jsonify({"error": "Invalid API key"}), 401
        return view(*args, **kwargs)

    return wrapped