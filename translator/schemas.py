"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .config import EngineKind


class DetectRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=100)


class DetectionResult(BaseModel):
    language: str = Field(description="ISO 639-1 code, or 'und' when unknown")
    confidence: float = Field(ge=0.0, le=1.0)


class DetectResponse(BaseModel):
    results: list[DetectionResult]


HtmlSupportLiteral = Literal["native", "prompt", "none"]
EngineStatusLiteral = Literal["ok", "throttled", "quota_exhausted", "error", "disabled"]


class EngineCapabilitiesInfo(BaseModel):
    html: HtmlSupportLiteral
    glossary: bool
    max_input_tokens: int | None = None


class EngineInfo(BaseModel):
    id: str
    kind: EngineKind
    model: str | None = None
    capabilities: EngineCapabilitiesInfo
    status: EngineStatusLiteral
    quota_resets_at: datetime | None = None


class EnginesResponse(BaseModel):
    engines: list[EngineInfo]


class TranslateTextRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=500)
    source_lang: str | None = None
    target_lang: str = "en"
    glossary: dict[str, str] = {}
    context: str | None = None
    engine: str | None = None


class TranslateTextResponse(BaseModel):
    translations: list[str]
    detected_source_lang: str | None = None
    engine: str
    new_terms: dict[str, str] = {}


class HtmlContext(BaseModel):
    novel_title: str | None = None
    synopsis: str | None = None
    chapter_title: str | None = None
    previous_chapter_tail: str | None = None


class TranslateHtmlRequest(BaseModel):
    html: str = Field(min_length=1)
    source_lang: str | None = None
    target_lang: str = "en"
    glossary: dict[str, str] = {}
    context: HtmlContext | None = None
    engine: str | None = None
    extract_terms: bool = True


class TranslateHtmlResponse(BaseModel):
    html: str
    detected_source_lang: str | None = None
    engine: str
    new_terms: dict[str, str] = {}
    warnings: list[str] = []


class ErrorDetail(BaseModel):
    code: str
    message: str
    retry_after_seconds: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
