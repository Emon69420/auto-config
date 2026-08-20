"""Pydantic models for the scraper config and API request/response payloads.

The ScraperConfig schema follows the spec response (section 3.1) and is kept
compatible with the hand-written files the Node worker reads, plus the spec's
new metadata fields (confidenceScore, metadata).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

# Spec section 9.2: sample_pages is 1-20, default 10. limit is >=1, default 5.
_MIN_SAMPLE_PAGES = 1
_MAX_SAMPLE_PAGES = 20
_DEFAULT_SAMPLE_PAGES = 10
_DEFAULT_LIMIT = 5


class ScraperConfig(BaseModel):
    """A per-host scraping config, matching the files the worker reads."""

    model_config = ConfigDict(extra="allow")

    websiteUrl: str
    seedUrls: list[str] = Field(default_factory=list)
    pathsToSkip: list[str] = Field(default_factory=list)
    scrapeWithGemini: bool = False
    limit: Optional[int] = None
    puppeteerOnly: bool = True
    requestsPerMinute: int = 500
    elementsToRemove: list[str] = Field(default_factory=list)
    geminiModel: str = "gemini-2.5-flash"
    stripImages: bool = True
    stripScripts: bool = True
    stripStyles: bool = True
    stripLinks: bool = True
    stripMeta: bool = True
    stripHead: bool = True
    stripNoscript: bool = True
    stripSvg: bool = True
    confidenceScore: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    """POST /generate payload (spec section 3.1 and 9.2)."""

    url: HttpUrl
    persist: bool = False
    sample_pages: int = Field(
        default=_DEFAULT_SAMPLE_PAGES,
        ge=_MIN_SAMPLE_PAGES,
        le=_MAX_SAMPLE_PAGES,
    )
    ai_refine: bool = True
    limit: Optional[int] = Field(default=_DEFAULT_LIMIT, ge=1)


class ValidateRequest(BaseModel):
    """POST /validate payload (spec section 3.2)."""

    config: ScraperConfig
    test_urls: list[HttpUrl] = Field(default_factory=list)


class HealRequest(BaseModel):
    """POST /heal payload (spec section 3.3)."""

    url: HttpUrl
    broken_selector: str
    field_name: str


class ValidationDetail(BaseModel):
    """Per-URL validation result (spec section 3.2)."""

    url: str
    reduction_pct: float
    main_content_length: int
    passed: bool


class ValidationReport(BaseModel):
    """The validation summary returned by the service (spec sections 3.1/3.2)."""

    passed: bool
    validation_score: float
    details: list[ValidationDetail] = Field(default_factory=list)


class HealResult(BaseModel):
    """POST /heal result (spec section 3.3)."""

    old: str
    new: str
    success: bool


class GenerateResult(BaseModel):
    """POST /generate success payload (spec section 3.1)."""

    host: str
    filename: str
    path: Optional[str] = None
    config: ScraperConfig
    validation: ValidationReport