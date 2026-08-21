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

Generate a per‑site scraper config for the given hostname. The endpoint **always returns JSON**; Node handles persistence.

**Request body** (`application/json`):

| Parameter | Type | Default / Required | Description |
|-----------|------|-------------------|-------------|
| `hostUrl` | `string` | **required** | Target hostname, e.g. `"quitci.com"` or `"www.quitci.com"`. Matched against config file names (lowercased, `www.` stripped/kept per hostname rules). |
| `sample_pages` | `int` | `10` (1–20) | Number of diverse pages to discover and analyze. |
| `ai_refine` | `bool` | `true` | Whether to run the LLM compiler for per‑site selector refinement. |
| `limit` | `int` or `null` | `5` | Max pages to crawl (`null` = full crawl). |
| `overrides` | `object` | `{}` | Per‑host overrides merged into the config (same shape as a standalone config file: `pathsToSkip`, `scrapeWithGemini`, `limit`, `puppeteerOnly`, `requestsPerMinute`, etc.). |
| Any additional keys | — | Passed through | Forwarded into the emitted config dict. The schema allows extra keys (`extra="allow"`). |

**Typical calls:**

```bash
# Minimal — generate and return full response
curl -X POST http://localhost:8000/generate \
  -H "x-api-key: $FLASK_INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"hostUrl":"quitci.com"}'

# With custom sample pages and limit
curl -X POST http://localhost:8000/generate \
  -H "x-api-key: $FLASK_INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"hostUrl":"quitci.com","sample_pages":15,"limit":10}'

# With overrides (e.g. custom paths to skip)
curl -X POST http://localhost:8000/generate \
  -H "x-api-key: $FLASK_INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"hostUrl":"quitci.com","overrides":{"pathsToSkip":["/cart","/account"]}}'
```

**Response (200 OK)** — complete pipeline result:

```json
{
  "host": "quitci.com",
  "config": {
    "websiteUrl": "quitci.com",
    "seedUrls": ["https://quitci.com/", "https://quitci.com/blog"],
    "pathsToSkip": ["/cart", "/login", "/wp-admin"],
    "scrapeWithGemini": true,
    "limit": 5,
    "puppeteerOnly": true,
    "requestsPerMinute": 500,
    "elementsToRemove": ["header", "footer", "nav", ".cookie-banner"],
    "geminiModel": "gemini-2.5-flash",
    "stripImages": true,
    "stripScripts": true,
    "stripStyles": true,
    "stripLinks": true,
    "stripMeta": true,
    "stripHead": true,
    "stripNoscript": true,
    "stripSvg": true,
    "confidenceScore": 0.84,
    "metadata": {
      "platforms": ["shopify"],
      "confidence": 0.84,
      "confidence_label": "high",
      "validation_score": 1.0
    }
  },
  "validation": {
    "passed": true,
    "validation_score": 1.0,
    "details": [
      {
        "url": "https://quitci.com/",
        "reduction_pct": 42.3,
        "main_content_length": 15230,
        "passed": true
      },
      {
        "url": "https://quitci.com/products/foo",
        "reduction_pct": 38.7,
        "main_content_length": 8921,
        "passed": true
      }
    ]
  },
  "confidence": 0.84,
  "confidence_label": "high",
  "platforms": ["shopify"],
  "degraded": false,
  "warnings": [
    {
      "selector": "main",
      "reason": "refused: content container",
      "kept": ["main#content", "div.main-content"]
    }
  ],
  "pruned": {
    "kept": 12,
    "dropped": 3,
    "refused": 2,
    "narrowed": 1
  }
}
```

**Response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `host` | `string` | Normalized hostname. |
| `config` | `object` | Full `ScraperConfig` (see schema below). |
| `validation` | `object` | ValidationReport with `passed`, `validation_score`, and per‑URL `details` (`url`, `reduction_pct`, `main_content_length`, `passed`). |
| `confidence` | `float` | Combined confidence score (0.0–1.0) from platform detection + validation. |
| `confidence_label` | `string` | `"high"` (≥0.8), `"medium"` (≥0.6), `"low"` (<0.6). |
| `platforms` | `list[str]` | Detected platforms (e.g. `["shopify"]`, `["wordpress","elementor"]`). |
| `degraded` | `bool` | `true` when validation failed but a content‑safe config was still produced. |
| `warnings` | `list[object]` | Content‑guard drops/refusals: each has `selector`, `reason`, and optional `kept` (narrowed replacements). |
| `pruned` | `object` | Counts: `kept`, `dropped`, `refused`, `narrowed` from the guard pass. |

**ScraperConfig schema (inside `config`):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `websiteUrl` | `string` | — | Normalized origin. |
| `seedUrls` | `list[str]` | `[]` | Seed URLs to crawl. |
| `pathsToSkip` | `list[str]` | `[]` | Paths to skip. |
| `scrapeWithGemini` | `bool` | `true` | Enable LLM clean step in production scraper. |
| `limit` | `int` or `null` | `null` | Max pages to crawl. |
| `puppeteerOnly` | `bool` | `true` | Force Playwright/Chromium. |
| `requestsPerMinute` | `int` | `500` | Rate limit for Node scraper. |
| `elementsToRemove` | `list[str]` | `[]` | CSS selectors to strip (post‑guard). |
| `geminiModel` | `string` | `gemini-2.5-flash` | Model for LLM clean. |
| `stripImages` / `stripScripts` / `stripStyles` / `stripLinks` / `stripMeta` / `stripHead` / `stripNoscript` / `stripSvg` | `bool` | `true` | Strip flags from `d.STRIP_FLAGS`. |
| `confidenceScore` | `float` | `0.0` | Confidence score. |
| `metadata` | `object` | `{}` | Platform, confidence, validation_score, etc. |

---

### `POST /validate`

Validate an existing config against a set of test URLs.

**Request body:**

```json
{
  "config": { /* full ScraperConfig object */ },
  "test_urls": ["https://quitci.com/", "https://quitci.com/blog"]
}
```

**Response (200 if passed, 400 if failed):**

```json
{
  "passed": true,
  "validation_score": 1.0,
  "details": [
    {
      "url": "https://quitci.com/",
      "reduction_pct": 42.3,
      "main_content_length": 15230,
      "passed": true
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `passed` | `bool` | Overall pass/fail (≥ threshold). |
| `validation_score` | `float` | Fraction of pages passing (0.0–1.0). |
| `details` | `list[object]` | Per‑URL results: `url`, `reduction_pct`, `main_content_length`, `passed`. |

---

### `POST /heal`

Repair a broken selector by rendering the live page, asking the LLM for a replacement, and verifying it matches the DOM.

**Request body:**

```json
{
  "url": "https://quitci.com/products/foo",
  "broken_selector": ".old-class",
  "field_name": "elementsToRemove"
}
```

**Response (200):**

```json
{
  "old": ".old-class",
  "new": "[data-testid='product-card']",
  "success": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `old` | `string` | Original broken selector. |
| `new` | `string` | Proposed replacement (equals `old` if no safe replacement found). |
| `success` | `bool` | `true` if replacement verified against live DOM. |

---

### `GET /health`

Liveness/readiness probe. Returns JSON with Playwright, LLM, and disk status.

**Response (200):**

```json
{
  "status": "ok",
  "playwright": "ok",
  "llm": "ok",
  "disk": "ok"
}
```

---

### `GET /metrics`

Prometheus metrics endpoint (text/plain). Exposes request latency, error counts, validation scores, etc.

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