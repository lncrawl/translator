"""Shapes that exist only to serve HTTP.

Engine listings, detection results, and the error envelope. The translation
request/response contract itself is shared with the embedded service and lives
in ``translator.schemas``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import EngineKind
from ..engines import CredentialField
from ..schemas import TextItem


class KindSchema(BaseModel):
    """Everything the dashboard needs to edit one engine kind.

    Capabilities are not here: they depend on an engine's own settings, so the
    listing reports them per engine (``EngineInfo.capabilities``).
    """

    kind: EngineKind
    credentials: list[CredentialField]
    provider_settings: dict[str, Any] = Field(
        description="JSON Schema of the kind's provider settings",
    )
    engine_settings: dict[str, Any] = Field(
        description="JSON Schema of the kind's engine settings",
    )


class ConfigSchema(BaseModel):
    """The editing contract: shared field schemas plus the per-kind ones.

    Generated from the Pydantic models, so the forms cannot drift from what
    the server accepts.
    """

    provider: dict[str, Any] = Field(
        description="JSON Schema of the settings every provider kind shares",
    )
    engine: dict[str, Any] = Field(
        description="JSON Schema of the settings every engine kind shares",
    )
    engine_entry: dict[str, Any] = Field(
        description="JSON Schema of an engine's fields outside its settings",
    )
    failure_policy: dict[str, Any]
    routing: dict[str, Any] = Field(
        description="JSON Schema of the routing lanes; titles are lane labels",
    )
    kinds: list[KindSchema]
    lanes: list[str]


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
