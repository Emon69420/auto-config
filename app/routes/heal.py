"""POST /heal (spec section 3.3).

Repairs a broken selector for a site, verifying the replacement matches the live
DOM before returning it.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.models.config import HealRequest
from app.routes.auth import get_current_settings, require_api_key
from app.services.async_util import run_async
from app.services.auto_healer import AutoHealer

bp = Blueprint("heal", __name__)


@bp.post("/heal")
@require_api_key
def heal_selector():
    settings = get_current_settings()
    payload = request.get_json(silent=True) or {}
    try:
        req = HealRequest.model_validate(payload)
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    healer = AutoHealer(settings=settings)
    try:
        result = run_async(
            healer.heal_broken_selector(
                str(req.url),
                req.broken_selector,
                req.field_name,
            )
        )
    finally:
        run_async(healer.close())
    return jsonify(result), 200