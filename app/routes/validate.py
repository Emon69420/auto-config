"""POST /validate (spec section 3.2).

Validates an existing config against a set of test URLs and returns the per-page
reduction/content details along with an overall score.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.models.config import ValidateRequest
from app.routes.auth import get_current_settings, require_api_key
from app.services.async_util import run_async
from app.services.validator import ConfigValidator

bp = Blueprint("validate", __name__)


@bp.post("/validate")
@require_api_key
def validate_config():
    settings = get_current_settings()
    payload = request.get_json(silent=True) or {}
    try:
        req = ValidateRequest.model_validate(payload)
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    test_urls = [str(u) for u in req.test_urls] or req.config.seedUrls
    validator = ConfigValidator(settings=settings)
    report = run_async(validator.validate_config(req.config.model_dump(), test_urls))
    return jsonify(report), (200 if report["passed"] else 400)