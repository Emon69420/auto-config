#!/usr/bin/env bash
set -euo pipefail

# Local development setup for the scraper-config-generator (WSL/Linux host).
# Creates a venv, installs dependencies, installs the Playwright Chromium build,
# and smoke-tests that every package imports.

cd "$(dirname "$0")"

echo "==> Creating virtualenv"
/usr/bin/python3 -m venv .venv

echo "==> Upgrading pip"
.venv/bin/pip install --upgrade pip -q

echo "==> Installing requirements"
.venv/bin/pip install -q -r requirements.txt

echo "==> Installing Playwright Chromium"
.venv/bin/playwright install chromium

echo "==> Smoke-testing imports"
.venv/bin/python - <<'PY'
import flask, pydantic, playwright, requests, structlog, prometheus_client
import bs4, lxml, google.genai
from flask_limiter import Limiter
print("all imports ok")
PY

echo "==> Setup complete"