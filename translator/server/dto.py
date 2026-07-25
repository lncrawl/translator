"""Shapes that exist only to serve HTTP.

Engine listings, detection results, and the error envelope. The translation
request/response contract itself is shared with the embedded service and lives
in ``translator.schemas``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..config import EngineKind
from ..schemas import TextItem


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
    # Base ISO 639-1 languages the engine covers; null means unrestricted.
    source_langs: list[str] | None = None
    target_langs: list[str] | None = None


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


class HealthResponse(BaseModel):
    status: Literal["ok", "unconfigured"]
    version: str
    engines_enabled: list[str]


class ErrorDetail(BaseModel):
    code: str
    message: str
    retry_after_seconds: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
