"""Flask application factory (spec sections 2.1 and 8).

Wires the routes, authentication, rate limiting, health check, and metrics into
one app. The service deliberately stays a thin shell: all pipeline logic lives
in app/services so it can be tested without the web layer.
"""

from __future__ import annotations

import logging
import os

import structlog
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config.settings import Settings, get_settings
from app.routes.auth import set_settings
from app.services import persistence

# --- metrics (spec section 8.2) ---
METRIC_REQUEST_COUNT = Counter(
    "config_generation_total", "Requests by endpoint and status",
    ["endpoint", "status"],
)
METRIC_DURATION = Histogram(
    "config_generation_duration_seconds", "Request duration by endpoint",
    ["endpoint"],
)
METRIC_VALIDATION_SCORE = Counter(
    "config_validation_total", "Validations by pass/fail", ["passed"],
)


def configure_logging(settings: Settings) -> None:
    """structlog-based logging (spec section 8.1)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
    )
    logging.basicConfig(level=level)


def create_app(settings: Settings | None = None) -> Flask:
    """Create and configure the Flask application."""
    settings = settings or get_settings()
    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    # explicit backend so flask-limiter does not warn about relying on the
    # default in-memory storage (spec section 9.3)
    app.config["RATELIMIT_STORAGE_URI"] = "memory://"

    configure_logging(settings)

    limiter = Limiter(
        key_func=lambda: request.remote_addr or "unknown",
        default_limits=[settings.rate_limit],
    )
    limiter.init_app(app)

    set_settings(app, settings)
    persistence.ensure_config_dir(settings.config_dir)

    from app.routes.generate import bp as generate_bp
    from app.routes.heal import bp as heal_bp
    from app.routes.validate import bp as validate_bp

    app.register_blueprint(generate_bp)
    app.register_blueprint(validate_bp)
    app.register_blueprint(heal_bp)

    @app.before_request
    def _track_request():
        request.ctx_start = float(__import__("time").time())

    @app.after_request
    def _record_metrics(response):
        endpoint = request.endpoint or "unknown"
        METRIC_REQUEST_COUNT.labels(endpoint=endpoint, status=str(response.status_code)).inc()
        start = getattr(request, "ctx_start", None)
        if start is not None:
            METRIC_DURATION.labels(endpoint=endpoint).observe(
                float(__import__("time").time()) - start
            )
        return response

    @app.get("/health")
    def health():  # spec section 8.3
        playwright_ok = _import_ok("playwright")
        llm_ok = bool(settings.genai_api_key)
        disk_ok = _config_dir_writable(settings)
        status = "healthy" if (playwright_ok and llm_ok and disk_ok) else "degraded"
        return jsonify({
            "status": status,
            "playwright": "ok" if playwright_ok else "missing",
            "llm": "ok" if llm_ok else "no api key",
            "disk": "ok" if disk_ok else "not writable",
        })

    @app.get("/metrics")
    def metrics():
        from flask import Response
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return app


def _import_ok(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _config_dir_writable(settings: Settings) -> bool:
    try:
        path = persistence.ensure_config_dir(settings.config_dir)
        test_file = os.path.join(path, ".write-test")
        with open(test_file, "w") as fh:
            fh.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")