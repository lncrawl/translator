"""Config models: providers, engines, routing, and failure policy.

A *provider* is an account at an API host — it owns the credentials and the
rate/quota limits, which are shared by every model used through it. An
*engine* is one model on one provider and is what routing lanes reference.

Anything specific to an engine *kind* — the endpoint, the credentials, the
model name — lives in that entry's ``settings`` bag, declared by the kind's
``Engine`` subclass. This layer keeps it as an opaque dict on purpose: it sits
below ``engines`` and may not import it, so per-kind validation belongs to
:func:`translator.engines.validate_config`, which ``ConfigStore`` runs for
every config that becomes live.

Credentials are ordinary settings fields marked as such. Providers that need
none (local servers) set ``requires_key: false``; until a required credential
is set the provider's engines stay disabled.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .legacy import (
    hoist_engine_settings,
    hoist_provider_settings,
    migrate_flat_engines,
)

# Every engine kind the service can build. The engine registry asserts its
# implementations cover exactly these, so the two can never drift.
EngineKind = Literal["openai", "deepl", "bing", "baidu"]

LANE_NAMES = ("chapter", "short_text")


class FailurePolicy(BaseModel):
    """Retry, fallback, and cooldown behavior of the router."""

    transient_retries: int = Field(
        default=2,
        ge=0,
        title="Transient retries",
        description="How many times to retry the same engine on a temporary"
        " error (timeout, rate limit, 5xx) before falling through to the next"
        " engine in the lane.",
    )
    backoff_base_seconds: float = Field(
        default=2.0,
        ge=0,
        title="Backoff base (s)",
        description="Base delay for exponential backoff between transient"
        " retries — the wait grows with each attempt.",
    )
    failure_threshold: int = Field(
        default=3,
        ge=1,
        title="Failure threshold",
        description="Consecutive hard failures on an engine before it is taken"
        " out of rotation and put on cooldown.",
    )
    cooldown_seconds: float = Field(
        default=300.0,
        ge=1,
        title="Cooldown (s)",
        description="How long an engine stays out of rotation after hitting the"
        " failure threshold, before the router tries it again.",
    )


def _override(name: str, **kwargs: Any) -> Any:
    """An optional mirror of one :class:`FailurePolicy` field, label and help
    text included, so the two can never describe the same knob differently."""
    base = FailurePolicy.model_fields[name]
    return Field(default=None, title=base.title, description=base.description, **kwargs)


class PartialFailurePolicy(BaseModel):
    """A per-provider or per-engine override of the global failure policy.

    Every field is optional and only the ones set are applied, resolved
    engine > provider > global. A slow local model wants fewer retries than the
    default; a 50-request-a-day lane wants a far longer cooldown.
    """

    transient_retries: int | None = _override("transient_retries", ge=0)
    backoff_base_seconds: float | None = _override("backoff_base_seconds", ge=0)
    failure_threshold: int | None = _override("failure_threshold", ge=1)
    cooldown_seconds: float | None = _override("cooldown_seconds", ge=1)

    def over(self, base: FailurePolicy) -> FailurePolicy:
        """``base`` with this override's set fields applied."""
        return base.model_copy(update=self.model_dump(exclude_none=True))


class ProviderConfig(BaseModel):
    """An API account. Everything but its identity lives in ``settings``.

    The kind's ``ProviderSettings`` model covers both the shared operational
    fields (rate limits, concurrency, failure-policy overrides) and whatever
    that kind adds (endpoint, credentials), so there is one place to look and
    one place to extend.
    """

    id: str = Field(min_length=1)
    kind: EngineKind = "openai"
    settings: dict[str, Any] = {}

    _hoist = model_validator(mode="before")(hoist_provider_settings)


class EngineConfig(BaseModel):
    """One model on one provider; what routing lanes reference.

    Like a provider, its configuration lives in ``settings``, validated against
    the model the *provider's* kind declares. ``enabled`` stays out on purpose:
    it is a lifecycle flag flipped straight from the engines list, and reading
    it should not require resolving the engine through its provider.
    """

    id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    enabled: bool = Field(
        default=True,
        title="Enabled",
        description="Disabled engines stay in the config but are never routed to.",
    )
    settings: dict[str, Any] = {}

    _hoist = model_validator(mode="before")(hoist_engine_settings)


class RoutingConfig(BaseModel):
    """Ordered engine preference per task type."""

    chapter: list[str] = Field(default=[], title="Chapter lane")
    short_text: list[str] = Field(default=[], title="Short-text lane")


class AppConfig(BaseModel):
    providers: list[ProviderConfig] = []
    engines: list[EngineConfig] = []
    routing: RoutingConfig = RoutingConfig()
    failure_policy: FailurePolicy = FailurePolicy()

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_engines(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return migrate_flat_engines(data)

    @model_validator(mode="after")
    def _validate_references(self) -> AppConfig:
        provider_ids = [p.id for p in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("duplicate provider ids in config")
        engine_ids = [e.id for e in self.engines]
        if len(engine_ids) != len(set(engine_ids)):
            raise ValueError("duplicate engine ids in config")
        known_providers = set(provider_ids)
        for engine in self.engines:
            if engine.provider not in known_providers:
                raise ValueError(
                    f"engine {engine.id!r} references unknown provider"
                    f" {engine.provider!r}"
                )
        known_engines = set(engine_ids)
        for lane_name in LANE_NAMES:
            for engine_id in getattr(self.routing, lane_name):
                if engine_id not in known_engines:
                    raise ValueError(
                        f"routing.{lane_name} references unknown engine {engine_id!r}"
                    )
        return self

    def provider(self, provider_id: str) -> ProviderConfig | None:
        return next((p for p in self.providers if p.id == provider_id), None)

    def engine(self, engine_id: str) -> EngineConfig | None:
        return next((e for e in self.engines if e.id == engine_id), None)
