# Running the Scraper Config Generator + curl examples

This service turns a website URL into a per-site **scraper config** (the same
shape the Node worker reads at `src/scrapers/configs/<host>.json`). It renders
the site in a real browser, validates before saving, and can auto-heal broken
selectors.

All examples assume the service is running on `http://localhost:8000` and that
`FLASK_INTERNAL_API_KEY` is set in the environment.

---

## 1. Prerequisites (first time only)

```bash
cp .env.example .env          # fill in GENAI_API_KEY and FLASK_INTERNAL_API_KEY
bash setup.sh                 # creates .venv, installs deps + Playwright Chromium
```

`.env` is gitignored — `setup.sh` does **not** commit it.

## 2. Start the service

**Option A — Flask dev server (quick):**

```bash
export GENAI_API_KEY="AIza...your-key"
export FLASK_INTERNAL_API_KEY="super-secret"
export SCRAPER_CONFIG_DIR=./configs
./.venv/bin/python app/main.py              # listens on 0.0.0.0:8000
```

**Option B — gunicorn (production-ish, n workers):**

```bash
set -a; source .env; set +a                 # loads the env vars from .env
./.venv/bin/gunicorn -w 4 -b 0.0.0.0:8000 'app.main:app'
```

**Option C — Docker:**

```bash
cp .env.example .env        # set keys
docker compose up --build
```

**Auth:** every `POST` requires the header `x-api-key: <FLASK_INTERNAL_API_KEY>`.
If the key is not configured the service fails closed (401).

---

## 3. curl examples

### Health check

```bash
curl -s http://localhost:8000/health | jq
```

```json
{ "status": "healthy", "playwright": "ok", "llm": "ok", "disk": "ok" }
```

`status` is `degraded` if Playwright is missing, no `GENAI_API_KEY`, or the
config dir is not writable.

### Prometheus metrics

```bash
curl -s http://localhost:8000/metrics | grep -E "config_generation|config_validation"
```

---

### Generate a config (render → analyze → LLM → validate)

```bash
curl -s -X POST http://localhost:8000/generate \
  -H "x-api-key: $FLASK_INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "url": "https://www.siddhivinayakhospitals.org",
        "persist": true,
        "sample_pages": 3,
        "ai_refine": true,
        "limit": 5
      }' | jq
```

Request fields (all optional except `url`):

| Field | Default | Meaning |
|-------|---------|---------|
| `url` | – | Site homepage (required) |
| `persist` | `false` | Write `configs/<host>.json` if validation passes |
| `sample_pages` | `10` | Pages sampled per site (`1`–`20`) |
| `ai_refine` | `true` | Let the LLM add site-specific selectors |
| `limit` | `5` | Deep-crawl limit written into the config; `null` = full crawl |

**200 — validated and saved** (`persist: true` wrote `configs/<host>.json`):

```json
{
  "host": "www.siddhivinayakhospitals.org",
  "filename": "www.siddhivinayakhospitals.org.json",
  "path": "configs/www.siddhivinayakhospitals.org.json",
  "config": {
    "websiteUrl": "https://www.siddhivinayakhospitals.org",
    "elementsToRemove": ["#beyond-chats-widget", "nav", "header", "footer", "..."],
    "pathsToSkip": ["/admin", "/login", "..."],
    "platforms": ["..."],
    "confidenceScore": 0.84,
    "metadata": {}
  },
  "validation": {
    "passed": true,
    "validation_score": 1.0,
    "details": [ { "url": "https://www.siddhivinayakhospitals.org", "reduction_pct": 100.0, "main_content_length": 14791, "passed": true } ]
  }
}
```

**Content guard (auto-trims destructive selectors):** before validation, the
service checks every candidate `elementsToRemove` against the rendered pages and
enforces a universal rule — *never remove the content*. Any selector that would
strip a page's text is **dropped or narrowed** to the exact non-content matches
(e.g. the Shopify catch-all `[id^="shopify-section-"]` becomes
`#shopify-section-header`, `#shopify-section-footer`, … and the content-bearing
section is excluded). This is what lets a brand-new site succeed on the first
try instead of failing a layout-specific edge case. The response's `pruned` and
`warnings` fields say what was changed.

**If validation still degrades** (site renders but the remaining config scores
below threshold), the service does **not** 400: it writes the best-effort,
content-safe config and returns it with `"degraded": true` plus `warnings`. A
hard **400** is reserved for malformed requests, and **502** for sites that
cannot be rendered at all.

**502 — rendering failed** (site unreachable / browser error). **400 — malformed request.**

---

### Validate an existing config

```bash
curl -s -X POST http://localhost:8000/validate \
  -H "x-api-key: $FLASK_INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "config": {
          "websiteUrl": "https://www.siddhivinayakhospitals.org",
          "elementsToRemove": ["nav", "header", "#beyond-chats-widget"],
          "pathsToSkip": ["/admin"]
        },
        "test_urls": ["https://www.siddhivinayakhospitals.org/about"]
      }' | jq
```

- `test_urls` is optional; defaults to `config.seedUrls`.
- HTTP **200** when it passes, **400** when it fails, with the full per-page
  `reduction_pct` / `main_content_length` / `passed` details.

---

### Auto-heal a broken selector

```bash
curl -s -X POST http://localhost:8000/heal \
  -H "x-api-key: $FLASK_INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "url": "https://www.siddhivinayakhospitals.org",
        "broken_selector": ".old-sidebar-class",
        "field_name": "elementsToRemove"
      }' | jq
```

```json
{ "old": ".old-sidebar-class", "new": ".sidebar", "success": true }
```

The replacement is verified against the live DOM before it is returned.

---

## 4. Useful notes

- **Rate limit:** 10 requests/min per client address (in-memory).
- **Generated configs** land in `SCRAPER_CONFIG_DIR` (default `./configs`).
- **Without `GENAI_API_KEY`** the pipeline still runs: it skips the LLM step and
  relies on the baseline + platform tables (`ai_refine` is effectively off).
- **Errors:** 401 bad `x-api-key`, 400 bad request / failed validation, 502
  rendering failure.
- Test suite:

  ```bash
  ./.venv/bin/python -m pytest        # 51 tests, offline
  ```