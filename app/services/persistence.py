"""Persistence layer (spec sections 2.1 and 3.1).

Saves a generated config to configs/<host>.json with its metadata, mirroring the
hand-written files the Node worker reads but adding the spec's confidenceScore and
metadata fields. All filename derivation is delegated to url_normalizer so the
"exact host, www preserved" rule is enforced in one place.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import get_settings
from app.utils.url_normalizer import config_filename, get_hostname

GENERATOR_VERSION = "1.0.0"


def ensure_config_dir(config_dir: str | None = None) -> str:
    """Resolve and create the config directory if it does not exist."""
    config_dir = config_dir or get_settings().config_dir
    path = Path(config_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _metadata(
    *,
    platforms: list[str],
    confidence: float,
    confidence_label: str,
    validation_score: float,
) -> dict[str, Any]:
    """The metadata block stored in the config and returned to the caller."""
    return {
        "platform_detected": list(platforms),
        "confidence": confidence_label,
        "validation_score": round(validation_score, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": GENERATOR_VERSION,
    }


def write_config(
    config: dict[str, Any],
    *,
    config_dir: str | None = None,
    platforms: list[str] | None = None,
    confidence: float = 0.0,
    confidence_label: str = "low",
    validation_score: float = 0.0,
) -> dict[str, str]:
    """Persist a generated config under its hostname.

    Returns {host, filename, path}. Raises ValueError when the config has no
    usable websiteUrl to derive a filename from.
    """
    website_url = config.get("websiteUrl")
    if not website_url:
        raise ValueError("config has no websiteUrl to derive a filename from")

    directory = ensure_config_dir(config_dir)
    filename = config_filename(website_url)
    if filename == "default.json":
        raise ValueError(f"could not derive a hostname from websiteUrl: {website_url!r}")

    to_write = dict(config)
    to_write["confidenceScore"] = round(confidence, 2)
    to_write["metadata"] = _metadata(
        platforms=platforms or [],
        confidence=confidence,
        confidence_label=confidence_label,
        validation_score=validation_score,
    )

    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_write, fh, indent=2)

    return {
        "host": get_hostname(website_url),
        "filename": filename,
        "path": path,
    }