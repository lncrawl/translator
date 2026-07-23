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

EngineKind = Literal["openai", "deepl", "nllb", "bing", "baidu"]

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
            options=provider.options,
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


# -- sparse overlay -----------------------------------------------------------
#
# The config file is a *sparse overlay* on the built-in defaults, not a full
# snapshot: it carries only what differs (api keys, custom providers/engines,
# routing tweaks) plus explicit removals. Defaults always come from code and
# merge underneath by id, so new or changed defaults reach existing installs
# without the file going stale. ``load_config`` merges; ``save_config`` diffs.


def _looks_legacy(data: dict[str, Any]) -> bool:
    """A pre-overlay flat config: an engine carrying provider-level fields
    (base_url/kind/...) inline instead of a ``provider`` reference. Such files
    predate the overlay format and are loaded standalone (defaults not merged)
    for backward compatibility."""
    engines = data.get("engines")
    if not isinstance(engines, list):
        return False
    markers = set(_LEGACY_PROVIDER_FIELDS)
    return any(
        isinstance(e, dict) and "provider" not in e and bool(markers & e.keys())
        for e in engines
    )


def _by_id(entries: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
    return out


def _apply_overlay(defaults: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge a sparse ``overlay`` onto ``defaults`` by id (overlay fields win).

    Defaults keep their order; overlay-only entries are appended. Ids in
    ``removed_providers``/``removed_engines`` drop the matching default, and a
    removed provider takes its engines with it. Routing lanes fall back to the
    default lane when the overlay omits them, then are pruned to engines that
    survived the merge.
    """
    removed_providers = set(overlay.get("removed_providers") or [])
    removed_engines = set(overlay.get("removed_engines") or [])
    overlay_providers = _by_id(overlay.get("providers"))
    overlay_engines = _by_id(overlay.get("engines"))

    providers: list[dict[str, Any]] = []
    seen_providers: set[str] = set()
    for base in defaults.get("providers") or []:
        pid = base["id"]
        if pid in removed_providers:
            continue
        providers.append({**base, **overlay_providers.get(pid, {})})
        seen_providers.add(pid)
    for pid, entry in overlay_providers.items():
        if pid not in seen_providers and pid not in removed_providers:
            providers.append(entry)
            seen_providers.add(pid)
    provider_ids = {p["id"] for p in providers}

    engines: list[dict[str, Any]] = []
    seen_engines: set[str] = set()
    for base in defaults.get("engines") or []:
        eid = base["id"]
        if eid in removed_engines:
            continue
        engines.append({**base, **overlay_engines.get(eid, {})})
        seen_engines.add(eid)
    for eid, entry in overlay_engines.items():
        if eid not in seen_engines and eid not in removed_engines:
            engines.append(entry)
            seen_engines.add(eid)
    engines = [e for e in engines if e.get("provider") in provider_ids]
    engine_ids = {e["id"] for e in engines}

    overlay_routing = overlay.get("routing") or {}
    default_routing = defaults.get("routing") or {}
    routing: dict[str, list[str]] = {}
    for lane in ("chapter", "short_text"):
        source = (
            overlay_routing[lane]
            if lane in overlay_routing
            else (default_routing.get(lane) or [])
        )
        routing[lane] = [i for i in source if i in engine_ids]

    merged: dict[str, Any] = {
        "providers": providers,
        "engines": engines,
        "routing": routing,
    }
    if "failure_policy" in overlay:
        merged["failure_policy"] = overlay["failure_policy"]
    elif "failure_policy" in defaults:
        merged["failure_policy"] = defaults["failure_policy"]
    return merged


def _diff_entry(current: BaseModel, base: BaseModel) -> dict[str, Any]:
    """Fields of ``current`` that differ from ``base``, always keeping ``id``."""
    cur = current.model_dump(mode="json")
    bas = base.model_dump(mode="json")
    diff: dict[str, Any] = {"id": cur["id"]}
    for key, value in cur.items():
        if key != "id" and bas.get(key) != value:
            diff[key] = value
    return diff


def build_overlay(config: AppConfig) -> dict[str, Any]:
    """The sparse overlay for ``config`` relative to the built-in defaults:
    only changed/custom entries, derived removals, and non-default routing."""
    from .defaults import DEFAULT_CONFIG

    defaults = AppConfig.model_validate(DEFAULT_CONFIG)
    default_providers = {p.id: p for p in defaults.providers}
    default_engines = {e.id: e for e in defaults.engines}
    overlay: dict[str, Any] = {}

    def _custom(model: BaseModel) -> dict[str, Any]:
        return model.model_dump(mode="json", exclude_defaults=True, exclude_none=True)

    provider_diffs: list[dict[str, Any]] = []
    for provider in config.providers:
        base = default_providers.get(provider.id)
        if base is None:
            provider_diffs.append(_custom(provider))
        else:
            diff = _diff_entry(provider, base)
            if len(diff) > 1:  # more than just the id — something changed
                provider_diffs.append(diff)
    if provider_diffs:
        overlay["providers"] = provider_diffs
    removed_providers = [
        pid for pid in default_providers if config.provider(pid) is None
    ]
    if removed_providers:
        overlay["removed_providers"] = removed_providers

    engine_diffs: list[dict[str, Any]] = []
    for engine in config.engines:
        engine_base = default_engines.get(engine.id)
        if engine_base is None:
            engine_diffs.append(_custom(engine))
        else:
            diff = _diff_entry(engine, engine_base)
            if len(diff) > 1:
                engine_diffs.append(diff)
    if engine_diffs:
        overlay["engines"] = engine_diffs
    removed_engines = [eid for eid in default_engines if config.engine(eid) is None]
    if removed_engines:
        overlay["removed_engines"] = removed_engines

    routing: dict[str, list[str]] = {}
    for lane in ("chapter", "short_text"):
        current = getattr(config.routing, lane)
        if current != getattr(defaults.routing, lane):
            routing[lane] = current
    if routing:
        overlay["routing"] = routing

    failure_policy = config.failure_policy.model_dump(exclude_defaults=True)
    if failure_policy:
        overlay["failure_policy"] = failure_policy
    return overlay


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from ``path``, $TRANSLATOR_CONFIG, or ./config.yml.

    Without a config file the built-in defaults apply — no file is needed to
    get started. When a file exists it is a *sparse overlay* on those defaults
    (see above): its entries merge onto the defaults by id, so newly added or
    updated default providers/engines reach the install automatically instead
    of the file going stale. Legacy flat configs are loaded standalone.
    """
    from .defaults import DEFAULT_CONFIG

    resolved = resolve_config_path(path)
    if not resolved.exists():
        logger.info("no config file at %s — using built-in defaults", resolved)
        return AppConfig.model_validate(DEFAULT_CONFIG)
    with resolved.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if _looks_legacy(data):
        logger.info("loading legacy flat config at %s (defaults not merged)", resolved)
        return AppConfig.model_validate(data)
    return AppConfig.model_validate(_apply_overlay(DEFAULT_CONFIG, data))


def save_config(config: AppConfig, path: str | Path) -> None:
    """Write the sparse overlay for ``config`` as YAML, atomically where the
    filesystem allows.

    Only what differs from the built-in defaults is written, so the file stays
    small and defaults keep flowing in on load. Falls back to an in-place write
    when rename fails — e.g. a Docker single-file bind mount, where the target
    cannot be replaced (EBUSY).
    """
    resolved = Path(path)
    text = yaml.safe_dump(build_overlay(config), sort_keys=False, allow_unicode=True)
    tmp = resolved.with_name(resolved.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(resolved)
    except OSError:
        tmp.unlink(missing_ok=True)
        resolved.write_text(text, encoding="utf-8")
