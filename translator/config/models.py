"""Config models: providers, engines, routing, and failure policy.

A *provider* is an account at an API host — it owns the credentials and the
rate/quota limits, which are shared by every model used through it. An
*engine* is one model on one provider and is what routing lanes reference.

Credentials: a provider carries its API key directly (``api_key``), set at
boot via the config file or remotely via the config API / web UI, and
persisted in that file. Providers that need no credentials (local servers)
set ``requires_key: false``; until a required key is set the provider's
engines stay disabled.

Legacy flat configs (engines carrying ``base_url``/``kind`` directly) are
migrated on load: each such engine gets an implicit provider with the same id.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Every engine kind the service can build. The engine registry asserts its
# implementations cover exactly these, so the two can never drift.
EngineKind = Literal["openai", "deepl", "bing", "baidu"]

# Engine fields that legacy flat entries hoisted into the implicit provider.
LEGACY_PROVIDER_FIELDS = (
    "kind",
    "base_url",
    "api_key",
    "requires_key",
    "rps",
    "rpm",
    "max_concurrency",
    "monthly_chars",
)

LANE_NAMES = ("chapter", "short_text")


class ProviderConfig(BaseModel):
    """An API account: base URL, credentials, and account-wide limits."""

    id: str = Field(min_length=1)
    kind: EngineKind = "openai"
    base_url: str | None = None
    api_key: str | None = None
    # Extra named credentials beyond api_key (e.g. baidu app_id/secret_key). The
    # fields a kind needs are declared on its Engine subclass (CREDENTIALS).
    options: dict[str, str] = {}
    requires_key: bool = True  # false marks keyless hosts, i.e. local servers
    # Client-side rate limits, shared by all engines on this provider.
    rps: float | None = Field(default=None, gt=0)
    rpm: float | None = Field(default=None, gt=0)
    max_concurrency: int = Field(default=1, ge=1)
    # Informational; quota exhaustion is detected from provider responses.
    monthly_chars: int | None = Field(default=None, gt=0)


class EngineConfig(BaseModel):
    """One model on one provider; what routing lanes reference."""

    id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str | None = None
    enabled: bool = True
    max_input_tokens: int | None = Field(default=None, gt=0)
    # Max source tokens per HTML chunk; defaults to a fraction of
    # max_input_tokens. Lower it for small local models, which stay
    # coherent on shorter passages.
    chunk_tokens: int | None = Field(default=None, gt=0)
    # Language coverage, as base ISO 639-1 codes. ``None`` means unrestricted,
    # which is what LLM lanes use (they translate any pair via the prompt).
    # Setting either list gates the engine to those languages so the router
    # rejects unsupported pairs before dispatching. Engines with intrinsic
    # coverage (baidu) declare it in code; these lists only narrow
    # it further.
    source_langs: list[str] | None = None
    target_langs: list[str] | None = None
    # Extra fields merged into every chat completion request — e.g.
    # {chat_template_kwargs: {enable_thinking: false}} to stop hybrid
    # reasoning models from burning tokens on thinking.
    extra_body: dict[str, Any] = {}


class ResolvedEngine(BaseModel):
    """An engine merged with its provider — what engine implementations
    and the router consume, so they never join the two themselves."""

    id: str
    provider_id: str
    kind: EngineKind
    base_url: str | None
    api_key: str | None = None
    options: dict[str, str] = {}
    requires_key: bool = True
    model: str | None
    enabled: bool
    max_input_tokens: int | None
    chunk_tokens: int | None
    source_langs: list[str] | None = None
    target_langs: list[str] | None = None
    extra_body: dict[str, Any] = {}

    def credential(self, key: str) -> str | None:
        """A named credential value: ``api_key`` or an entry in ``options``."""
        if key == "api_key":
            return self.api_key
        return self.options.get(key)


class RoutingConfig(BaseModel):
    chapter: list[str] = []
    short_text: list[str] = []


class FailurePolicy(BaseModel):
    """Retry, fallback, and cooldown behavior of the router."""

    # Same-engine retries for transient errors (5xx, timeouts, short 429s).
    transient_retries: int = Field(default=2, ge=0)
    backoff_base_seconds: float = Field(default=2.0, ge=0)
    # After this many consecutive failed requests an engine is benched...
    failure_threshold: int = Field(default=3, ge=1)
    # ...for this long, instead of being retried first-in-lane every request.
    cooldown_seconds: float = Field(default=300.0, ge=1)


class AppConfig(BaseModel):
    providers: list[ProviderConfig] = []
    engines: list[EngineConfig] = []
    routing: RoutingConfig = RoutingConfig()
    failure_policy: FailurePolicy = FailurePolicy()

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_engines(cls, data: Any) -> Any:
        """Flat engine entries (with base_url/kind inline) become an engine
        plus an implicit provider sharing the engine's id."""
        if not isinstance(data, dict):
            return data
        engines = data.get("engines")
        if not isinstance(engines, list):
            return data
        providers = list(data.get("providers") or [])
        migrated = []
        for entry in engines:
            if isinstance(entry, dict) and "provider" not in entry:
                provider = {"id": entry.get("id")}
                for field_name in LEGACY_PROVIDER_FIELDS:
                    if field_name in entry:
                        provider[field_name] = entry[field_name]
                providers.append(provider)
                entry = {
                    key: value
                    for key, value in entry.items()
                    if key in EngineConfig.model_fields
                }
                entry["provider"] = provider["id"]
            migrated.append(entry)
        return {**data, "providers": providers, "engines": migrated}

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
        for provider in self.providers:
            if provider.kind == "openai" and not provider.base_url:
                raise ValueError(
                    f"provider {provider.id!r}: openai kind requires base_url"
                )
        return self

    def provider(self, provider_id: str) -> ProviderConfig | None:
        return next((p for p in self.providers if p.id == provider_id), None)

    def engine(self, engine_id: str) -> EngineConfig | None:
        return next((e for e in self.engines if e.id == engine_id), None)

    def resolved(self, engine_id: str) -> ResolvedEngine | None:
        engine = self.engine(engine_id)
        if engine is None:
            return None
        provider = self.provider(engine.provider)
        assert provider is not None  # _validate_references guarantees this
        return ResolvedEngine(
            id=engine.id,
            provider_id=provider.id,
            kind=provider.kind,
            base_url=provider.base_url,
            api_key=provider.api_key,
            options=provider.options,
            requires_key=provider.requires_key,
            model=engine.model,
            enabled=engine.enabled,
            max_input_tokens=engine.max_input_tokens,
            chunk_tokens=engine.chunk_tokens,
            source_langs=engine.source_langs,
            target_langs=engine.target_langs,
            extra_body=engine.extra_body,
        )

    def resolved_engines(self) -> list[ResolvedEngine]:
        resolved = [self.resolved(e.id) for e in self.engines]
        return [r for r in resolved if r is not None]
