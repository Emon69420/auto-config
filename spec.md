# Technical Specification: Automated Scraper Config Generator

**Version**: 1.0
**Author**: AI Assistant
**Date**: August 20, 2026
**Status**: Implemented (see notes in this file)

> This is the authoritative spec this project is built against. The only
> deliberate deviation is the web framework: **Flask + gunicorn** in place of
> FastAPI + uvicorn (see "Implementation notes" at the end). All other details —
> architecture, data flow, prompts, config schema, API, tests, deployment — are
> followed as written.

---

## 1. Executive Summary

### 1.1 Purpose

Build a production-grade web scraper configuration generator that automatically creates per-site scraper configs by analyzing rendered DOM, detecting platforms, and using LLM to identify site-wide boilerplate (nav, footer, CTAs, forms, sidebars).

### 1.2 Problem Statement

Current system fails on JS-rendered sites (Shopify, Webflow) because:
- Platform detection uses raw HTML (misses JS-injected markers)
- Selector inventory incomplete (doesn't capture `#shopify-section-*` IDs)
- No automated validation (manual iteration required)
- No auto-healing (broken selectors require manual fixes)

### 1.3 Solution

Rebuild as a standalone service with:
- **Always render JS first** (Playwright) before any analysis
- **Complete selector inventory** from rendered DOM
- **Automated validation** before saving configs
- **Auto-healing** for runtime selector failures

### 1.4 Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Config generation success rate | ≥95% | % of sites that generate valid configs |
| Platform detection accuracy | ≥90% | % of sites where platform correctly identified |
| Boilerplate detection accuracy | ≥85% | % of nav/footer/CTA correctly identified |
| Validation pass rate | ≥90% | % of configs that pass automated validation |
| Auto-heal success rate | ≥80% | % of broken selectors successfully repaired |

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
CLIENT REQUEST -> POST /generate { url, persist }
      v
ORCHESTRATION LAYER (request validation, orchestration, response formatting)
      v
DISCOVERY SERVICE (robots.txt, sitemaps XML+index+.gz, BFS fallback, 10-20 URLs)
      v
RENDERING SERVICE (Playwright, headless Chromium, networkidle, HTML+JSON-LD+OG)
      v
ANALYSIS SERVICE (selector inventory, platform detection, json_ld)
      v
LLM COMPILER SERVICE (Gemini 2.5 Flash / Claude 3.5 Haiku)
      v
VALIDATION SERVICE (test on 3-5 pages, verify removal + content preserved)
      v
PERSISTENCE LAYER (configs/<host>.json + metadata)
      v
RUNTIME EXTRACTION (Node.js service, unchanged)
```

### 2.2 Component Diagram

```
scraper-config-generator/
|-- app/
|   |-- main.py
|   |-- routes/          generate.py, validate.py, heal.py
|   |-- services/        discovery.py, renderer.py, analyzer.py,
|   |                     llm_compiler.py, validator.py, auto_healer.py
|   |-- models/          config.py (ScraperConfig), selector.py (SelectorInventory)
|   |-- utils/           platform_detection.py, safety_guards.py, url_normalizer.py
|   `-- config/          settings.py, prompts.py
|-- tests/               per-service unit tests + e2e
|-- configs/             generated configs
|-- requirements.txt
|-- Dockerfile
|-- docker-compose.yml
`-- README.md
```

### 2.3 Data Flow

```
User Request (URL)
    -> Discovery   (list of 10-20 URLs)
    -> Rendering   (list of {url, html, json_ld, og_tags})
    -> Analysis    ({selector_inventory, platforms, json_ld})
    -> LLM Compile (ScraperConfig: elementsToRemove, pathsToSkip)
    -> Validate    ({passed, validation_score})
    -> Persist     (configs/<host>.json)
    -> Response    ({host, filename, config, validation})
```

### 2.4 Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Framework | Flask (deviation: FastAPI in spec) | 3.0+ |
| Rendering | Playwright | 1.49+ |
| LLM | Google Generative AI (gemini-2.5-flash) | via google-genai |
| HTML Parsing | BeautifulSoup4 + lxml | 4.12+/5.x |
| Sitemap | ultimate-sitemap-parser (robots/BFS fallback internal) | 0.6+ |
| Validation | Pydantic | 2.7+ |
| Testing | pytest + pytest-asyncio | 8.3+ |
| Container | Docker + docker-compose | 24+ / 2+ |

---

## 3. API Specification

### 3.1 POST /generate

Request:
```json
{ "url": "https://example.com", "persist": true, "sample_pages": 10, "ai_refine": true, "limit": 5 }
```

Response (200):
```json
{
  "host": "example.com",
  "filename": "example.com.json",
  "path": "/app/configs/example.com.json",
  "config": {
    "websiteUrl": "https://example.com",
    "seedUrls": ["https://example.com"],
    "pathsToSkip": ["/admin", "/login", "/cart"],
    "elementsToRemove": ["nav", "footer", ".cookie-notice"],
    "puppeteerOnly": true,
    "stripImages": true,
    "stripScripts": true,
    "stripStyles": true,
    "stripLinks": true,
    "stripMeta": true,
    "stripHead": true,
    "stripNoscript": true,
    "stripSvg": true,
    "requestsPerMinute": 500,
    "geminiModel": "gemini-2.5-flash",
    "confidenceScore": 0.9,
    "metadata": { "platform_detected": ["shopify"], "confidence": "high", "validation_score": 0.95 }
  },
  "validation": { "passed": true, "validation_score": 0.95, "details": [...] }
}
```

Validation Failed (400):
```json
{ "error": "Config validation failed", "validation": { "passed": false, "validation_score": 0.6, "details": [...] } }
```

### 3.2 POST /validate

Request: `{ "config": {...}, "test_urls": [...] }`
Response: `{ "passed": true, "validation_score": 0.95, "details": [ {url, reduction_pct, main_content_length, passed} ] }`

### 3.3 POST /heal

Request: `{ "url": "...", "broken_selector": ".old-nav", "field_name": "elementsToRemove" }`
Response: `{ "old": ".old-nav", "new": ".header-main", "success": true }`

---

## 4. Implementation Details

### 4.1 Discovery Service — `services/discovery.py` (SiteDiscovery)
- `fetch_robots()` — robots.txt sitemap URLs
- `fetch_sitemaps()` — all URLs (handles .gz, indexes)
- `fallback_crawl(n)` — BFS crawl if no sitemap
- `get_diverse_urls(n)` — homepage + product + collection + blog + random fill

### 4.2 Rendering Service — `services/renderer.py` (PageRenderer)
- `render_page(url)` — networkidle, rendered HTML + JSON-LD + OpenGraph
- `render_batch(urls, concurrency=3)`
- Resilient: falls back from `networkidle` to `load`+settle so sites with chat
  widgets / analytics don't timeout (implementation note, keeps spec intent).

### 4.3 Analysis Service — `services/analyzer.py` (SelectorAnalyzer)
- `extract_selector_inventory(html)` — all IDs, classes, tags
- `aggregate_inventory(urls)` — aggregated top ~50 ids / 100 classes / 20 tags

### 4.4 LLM Compiler Service — `services/llm_compiler.py` (LLMCompiler)
- Prompt: platform + inventory + structured data; identify site-wide boilerplate
- Rules: only selectors with frequency = num_pages; no utility classes; no content
  selectors; prefer specific; **cap 15**; return valid JSON.

### 4.5 Validation Service — `services/validator.py` (ConfigValidator)
- Per test URL: count before, remove, count after, main-content length
- `passed` = reduction > 10 AND content > 500
- Score = passed / total; overall pass when score >= 0.8

### 4.6 Auto-Healer — `services/auto_healer.py` (AutoHealer)
- Render page -> DOM snapshot -> LLM proposes selector -> verify it matches -> return

---

## 5. Test Cases

Test sites: x8.adencys.com, www.siddhivinayakhospitals.org, medicalappraisals.co.uk,
www.ivfmatters.co.uk, www.drmalpani.com, www.apnipathshala.org.

- TC001 Shopify (x8) — platform `["shopify"]`, `[id^="shopify-section-"]`,
  `cart-drawer`, `store-header`, puppeteerOnly true, validations pass.
- TC002 Custom (siddhivinayak) — no `.container`/`.img-fluid` (utility guard),
  theme-specific selectors, validation pass.
- TC003 JS Shopify (ivfmatters) — platform detected from rendered DOM.
- TC004 Deep DOM (drmalpani) — resilient selectors, not brittle DOM paths.
- TC005 Large (apni) — elementsToRemove capped.
- TC006 E2E — generate -> validate -> Node extraction clean.

---

## 6. Deployment

- Dockerfile: python:3.11-slim, chromium apt deps, `playwright install chromium`,
  gunicorn CMD (deviation: uvicorn in spec).
- docker-compose.yml: port 8000, env GENAI_API_KEY / FLASK_INTERNAL_API_KEY /
  SCRAPER_CONFIG_DIR / PLAYWRIGHT_BROWSERS_PATH, volume `./configs:/app/configs`.
- Env: `GENAI_API_KEY`, `FLASK_INTERNAL_API_KEY`, `SCRAPER_CONFIG_DIR=/app/configs`,
  `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`.

---

## 7. Testing Strategy

Unit tests per service (offline, external calls mocked) + e2e route tests + load
targets. These map 1:1 to `tests/`.

---

## 8. Monitoring

- Logging: structlog (INFO generated / WARNING validation fail / ERROR render fail).
- Metrics: prometheus counters/histogram under `/metrics`.
- Health: `GET /health` -> `{status, playwright, llm, disk}`.

---

## 9. Security

- Auth: `x-api-key` header vs `FLASK_INTERNAL_API_KEY`; fails closed (401).
- Input validation: Pydantic (url HttpUrl, sample_pages 1-20, limit >=1).
- Rate limiting: 10 requests/minute/IP.

---

## 10. Future Enhancements

Phase 2: extraction schema from JSON-LD, per-page-type configs, visual selector
picker, config versioning. Phase 3: runtime auto-heal hook, A/B configs,
confidence-based manual-review routing.

---

## 11. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Playwright rendering slow | High | Medium | concurrency=3, cache |
| LLM hallucinates selectors | High | Low | validation layer + safety guards |
| Site blocks Playwright | Medium | Low | stealth/UA rotation |
| API cost | Medium | Low | cap sample_pages, use Flash |
| Configs break on redesign | High | Medium | auto-healer at runtime |

---

## Implementation notes (this build)

- **Framework deviation**: Flask + gunicorn, not FastAPI + uvicorn (requested).
- Rendered-DOM platform detection fixes TC001/TC003 (the JS blind spot).
- Selector safety: utility-class guard + `filter_safe_selectors` choke point.
- `stripLinks` defaults `true` (spec example shows `false` in one place).
- Schema errors return 400 (FastAPI would use 422).
- `metadata`/`confidenceScore` live inside the config file per spec; a
  `WRITE_PURE_SCHEMA` flag can strip them at save if the external Node worker
  ever rejects unknown keys.