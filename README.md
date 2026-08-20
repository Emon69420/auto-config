# Scraper Config Generator

A standalone service that turns a website address into a per-site **scraper
config** automatically — the same kind of file a human once hand-wrote for the
Node extraction service (`beyondchats-node/src/scrapers/configs/<host>.json`).

It is built from the technical spec (**spec.md**) and deviates from it in one
deliberate way: it is a **Flask** service (gunicorn) rather than FastAPI/uvicorn.
Everything else — architecture, data flow, prompts, config schema, API, tests,
deployment — follows the spec.

## Why this exists

Generating configs by hand is the bottleneck for rolling website sync out.
Sites differ (Shopify, Elementor, custom), many render content in JavaScript,
and a bad selector silently strips the very text a chatbot should answer from.
This service fixes all three by:

1. **Rendering with a real browser first** (Playwright/Chromium) so analysis sees
   the true DOM, not a JS-framework shell.
2. **Validating before saving** — it tests the config on sample pages, requiring
   boilerplate to actually be removed while main content survives (score ≥ 0.8),
   and auto-prunes any selector that would strip the content.
3. **Auto-healing** broken selectors at runtime via `POST /heal`.

## Pipeline

```
URL → Discovery → Rendering (Playwright) → Analysis → LLM Compiler → Compose
     → Validate → Persist → (unchanged Node worker)
```

## Quickstart (local)

```bash
cp .env.example .env      # fill in GENAI_API_KEY and FLASK_INTERNAL_API_KEY
bash setup.sh             # venv + deps + Playwright Chromium
export GENAI_API_KEY=... FLASK_INTERNAL_API_KEY=... SCRAPER_CONFIG_DIR=./configs
./.venv/bin/python app/main.py     # Flask on :8000
```

Or with Docker:

```bash
cp .env.example .env
docker compose up --build
```

## Configuration

All settings come from environment variables (defaults in
`app/config/settings.py`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `GENAI_API_KEY` | – | Gemini key for the LLM compiler/healer |
| `FLASK_INTERNAL_API_KEY` | – | `x-api-key` required on every POST (fails closed) |
| `SCRAPER_CONFIG_DIR` | `./configs` | Where generated configs are written |
| `PLAYWRIGHT_BROWSERS_PATH` | – | Playwright browser location |
| `DEFAULT_SAMPLE_PAGES` | 10 | Pages sampled per site (1–20) |
| `DEFAULT_LIMIT` | 5 | `limit` written into a generated config |
| `MAX_AI_SELECTORS` | 15 | Cap on LLM-chosen selectors |
| `VALIDATION_THRESHOLD` | 0.8 | Pass threshold for validation score |

## API

All POST routes require the header `x-api-key: <FLASK_INTERNAL_API_KEY>`.

### `POST /generate`

```bash
curl -X POST http://localhost:8000/generate \
  -H "x-api-key: $FLASK_INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.siddhivinayakhospitals.org","persist":true}'
```

- `persist: true` writes `configs/<host>.json`. Destructive selectors are
  auto-pruned by the content guard before writing; if validation still degrades
  the content-safe config is written anyway and flagged `degraded: true`.
- Optional fields: `sample_pages` (default 10), `ai_refine` (default true),
  `limit` (default 5; `null` = full crawl).

**200** → `{host, filename, path, config, validation}` where `config` carries
`confidenceScore` and `metadata`.

### `POST /validate`

Validate an existing config against URLs. **200** when it passes, **400** when not.

### `POST /heal`

Repair a broken selector. Body: `{url, broken_selector, field_name}` →
`{old, new, success}`.

### `GET /health` · `GET /metrics`

Health of Playwright/LLM/disk, and Prometheus metrics.

## Tests

```bash
./.venv/bin/python -m pytest
```

Unit tests mock all external calls (renderer, LLM, validator) so the suite runs
offline. E2E route tests assert the HTTP contract. The spec's manual test cases
(TC001–TC006) map to `spec.md §5.3/5.4`; run them against spec test sites once a
real `GENAI_API_KEY` is configured.

## Layout

```
app/
  config/     settings.py, prompts.py, defaults.py
  models/     Pydantic ScraperConfig, SelectorInventory, request/result schemas
  utils/      url_normalizer, platform_detection, safety_guards
  services/   discovery, renderer, analyzer, llm_compiler,
              validator, auto_healer, persistence, generator_service
  routes/     generate.py, validate.py, heal.py, auth.py
  main.py     Flask factory, health, metrics, rate limiting
tests/        unit + route-level tests
configs/      generated config output
```

## Notes / deliberate deviations from spec

- **Framework:** Flask + gunicorn instead of FastAPI + uvicorn.
- `stripLinks` defaults to `true` (spec's example response shows `false`).
- Schema errors return **400** (FastAPI would use 422).
- The spec's `metadata`/`confidenceScore` live inside the config file. The Node
  worker that consumes these files is external; if unknown keys ever break it, a
  `WRITE_PURE_SCHEMA` flag can strip them at save time.