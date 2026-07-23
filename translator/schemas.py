"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from .config import EngineKind
from .languages import canonicalize

# Upper bounds on request payloads. Generous for real novel content while
# keeping a single request from consuming unbounded memory or engine quota.
MAX_TEXT_CHARS = 10_000
MAX_HTML_CHARS = 1_000_000
MAX_CONTEXT_CHARS = 5_000

TextItem = Annotated[str, StringConstraints(max_length=MAX_TEXT_CHARS)]
ContextStr = Annotated[str, StringConstraints(max_length=MAX_CONTEXT_CHARS)]
# BCP 47 tag: ISO 639-1 primary subtag + optional script/region subtag,
# canonicalized (zh-tw -> zh-Hant, pt-br -> pt-BR). Invalid tags 422.
LangCode = Annotated[str, AfterValidator(canonicalize)]


class DetectRequest(BaseModel):
    texts: list[TextItem] = Field(min_length=1, max_length=100)


class DetectionResult(BaseModel):
    language: str = Field(
        description="ISO 639-1 language code, or 'und' when unknown",
    )
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
    provider: str
    kind: EngineKind
    model: str | None = None
    # Effective state: enabled in config and the provider's key is set.
    enabled: bool = True
    capabilities: EngineCapabilitiesInfo
    status: EngineStatusLiteral
    # When a quota-exhausted or cooling-down engine becomes eligible again.
    retry_at: datetime | None = None
    # Provider concurrency slots (shared by the provider's engines): how many
    # are free right now and the total. None when the engine isn't active.
    slots_free: int | None = None
    slots_total: int | None = None


class EnginesResponse(BaseModel):
    engines: list[EngineInfo]


class TranslateTextRequest(BaseModel):
    texts: list[TextItem] = Field(min_length=1, max_length=500)
    source_lang: LangCode | None = Field(
        default=None,
        description="ISO 639-1 language code; autodetected when unset",
    )
    target_lang: LangCode = Field(
        default="en",
        description="ISO 639-1 language code",
    )
    glossary: dict[str, str] = {}
    context: ContextStr | None = None
    engine: str | None = None


class TranslateTextResponse(BaseModel):
    translations: list[str]
    detected_source_lang: str | None = None
    engine: str
    new_terms: dict[str, str] = {}


class HtmlContext(BaseModel):
    novel_title: ContextStr | None = None
    synopsis: ContextStr | None = None
    chapter_title: ContextStr | None = None
    previous_chapter_tail: ContextStr | None = None


class TranslateHtmlRequest(BaseModel):
    html: str = Field(min_length=1, max_length=MAX_HTML_CHARS)
    source_lang: LangCode | None = Field(
        default=None,
        description="ISO 639-1 language code; autodetected when unset",
    )
    target_lang: LangCode = Field(
        default="en",
        description="ISO 639-1 language code",
    )
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
