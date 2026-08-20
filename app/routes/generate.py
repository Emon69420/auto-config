"""POST /generate (spec section 3.1).

Generates a config for a website. `persist: true` writes it to the config dir
and refuses to save a config that fails validation (400).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.models.config import GenerateRequest
from app.routes.auth import get_current_settings, require_api_key
from app.services import generator_service
from app.services.exceptions import ConfigError, RenderingError, ValidationFailed

bp = Blueprint("generate", __name__)


@bp.post("/generate")
@require_api_key
def generate_config():
    settings = get_current_settings()
    payload = request.get_json(silent=True) or {}
    try:
        req = GenerateRequest.model_validate(payload)
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    try:
        result = generator_service.generate(
            str(req.url),
            persist=req.persist,
            sample_pages=req.sample_pages,
            ai_refine=req.ai_refine,
            limit=req.limit,
            settings=settings,
        )
    except ConfigError as exc:
        return jsonify({"error": str(exc)}), 400
    except RenderingError as exc:
        return jsonify({"error": str(exc)}), 502
    except ValidationFailed as exc:
        return jsonify({"error": str(exc), "validation": exc.report}), 400

    return jsonify(result), 200