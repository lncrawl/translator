"""Configuration: providers, engines, routing, and failure policy.

A *provider* is an account at an API host — it owns the credentials and the
rate/quota limits, which are shared by every model used through it. An
*engine* is one model on one provider and is what routing lanes reference.

Credentials: a provider carries its API key directly (``api_key``), set at
boot via this file or remotely via the config API / web UI, and persisted
in the config file. Providers that need no credentials (local servers)
set ``requires_key: false``; until a required key is set the provider's
engines stay disabled.

Legacy flat configs (engines carrying ``base_url``/``kind`` directly) are
migrated on load: each such engine gets an implicit provider with the same id.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yml"
CONFIG_PATH_ENV = "TRANSLATOR_CONFIG"

EngineKind = Literal["openai", "deepl", "nllb"]

# Engine fields that legacy flat entries hoisted into the implicit provider.
_LEGACY_PROVIDER_FIELDS = (
    "kind",
    "base_url",
    "api_key",
    "requires_key",
    "rps",
    "rpm",
    "max_concurrency",
    "monthly_chars",
)


class ProviderConfig(BaseModel):
    """An API account: base URL, credentials, and account-wide limits."""

    id: str = Field(min_length=1)
    kind: EngineKind = "openai"
    base_url: str | None = None
    # Direct token, persisted in the config file; set at boot or remotely
    # via the config API / web UI. Engines stay disabled until the key is
    # set — unless the provider needs none (requires_key: false, e.g. a
    # local server; nllb never needs one).
    api_key: str | None = None
    requires_key: bool = True
    # Client-side rate limits, shared by all engines on this provider.
    rps: float | None = Field(default=None, gt=0)
    rpm: float | None = Field(default=None, gt=0)
    max_concurrency: int = Field(default=1, ge=1)
    # Informational; quota exhaustion is detected from provider responses.
    monthly_chars: int | None = Field(default=None, gt=0)

    @property
    def key_present(self) -> bool:
        """True when no key is required or one is set."""
        if self.kind == "nllb" or not self.requires_key:
            return True
        return bool(self.api_key)


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
    requires_key: bool = True
    model: str | None
    enabled: bool
    max_input_tokens: int | None
    chunk_tokens: int | None
    extra_body: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        """Enabled in config and the provider's key (if required) is set."""
        if not self.enabled:
            return False
        if self.kind == "nllb" or not self.requires_key:
            return True
        return bool(self.api_key)


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
                for field_name in _LEGACY_PROVIDER_FIELDS:
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
        for lane_name in ("chapter", "short_text"):
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
            requires_key=provider.requires_key,
            model=engine.model,
            enabled=engine.enabled,
            max_input_tokens=engine.max_input_tokens,
            chunk_tokens=engine.chunk_tokens,
            extra_body=engine.extra_body,
        )

    def resolved_engines(self) -> list[ResolvedEngine]:
        resolved = [self.resolved(e.id) for e in self.engines]
        return [r for r in resolved if r is not None]


def resolve_config_path(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from ``path``, $TRANSLATOR_CONFIG, or ./config.yml.

    Without a config file the built-in defaults apply: every known free
    provider is pre-wired and engines activate when their provider's key
    env var is set — no file is needed to get started.
    """
    from .defaults import DEFAULT_CONFIG

    resolved = resolve_config_path(path)
    if not resolved.exists():
        logger.info("no config file at %s — using built-in defaults", resolved)
        return AppConfig.model_validate(DEFAULT_CONFIG)
    with resolved.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    return AppConfig.model_validate(data)


def save_config(config: AppConfig, path: str | Path) -> None:
    """Write config as YAML, atomically where the filesystem allows.

    Falls back to an in-place write when rename fails — e.g. a Docker
    single-file bind mount, where the target cannot be replaced (EBUSY).
    """
    resolved = Path(path)
    data = config.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    tmp = resolved.with_name(resolved.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(resolved)
    except OSError:
        tmp.unlink(missing_ok=True)
        resolved.write_text(text, encoding="utf-8")
