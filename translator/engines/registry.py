"""The kind → implementation table.

One place maps a config ``kind`` to the class that implements it. Construction,
capability description, credential discovery, settings validation and the join
of a provider with its engine all read from it, so adding a backend means
writing one class and listing it here. The module-level checks keep the table,
the ``EngineKind`` literal, and the settings declarations honest.
"""

from __future__ import annotations

from typing import Any, get_args

from pydantic import ValidationError

from ..config import AppConfig, EngineKind
from .baidu import BaiduEngine
from .base import (
    CredentialField,
    Engine,
    EngineCapabilities,
    EngineSettings,
    ProviderSettings,
    ResolvedEngine,
    Settings,
    field_flag,
)
from .bing import BingEngine
from .deepl import DeepLEngine
from .openai_compat import OpenAICompatEngine

_IMPLEMENTATIONS: tuple[type[Engine], ...] = (
    OpenAICompatEngine,
    DeepLEngine,
    BingEngine,
    BaiduEngine,
)

ENGINE_CLASSES: dict[EngineKind, type[Engine]] = {
    cls.KIND: cls for cls in _IMPLEMENTATIONS
}

assert set(ENGINE_CLASSES) == set(get_args(EngineKind)), (
    "engine implementations and the EngineKind literal disagree:"
    f" {sorted(set(ENGINE_CLASSES) ^ set(get_args(EngineKind)))}"
)


def _undeclared_secrecy() -> list[str]:
    """Settings fields that never say whether they hold a secret.

    Secrecy drives redaction, and as plain Pydantic fields a base URL and an
    API token are indistinguishable — a forgotten marker would leak a token
    through ``GET /config`` with nothing failing. Requiring the marker turns
    that into an import error.
    """
    missing = []
    for kind, cls in ENGINE_CLASSES.items():
        for scope, model in (
            ("provider", cls.PROVIDER_SETTINGS),
            ("engine", cls.ENGINE_SETTINGS),
        ):
            for name in model.model_fields:
                if field_flag(model, name, "secret") is None:
                    missing.append(f"{kind}.{scope}.{name}")
    return missing


_MISSING_SECRECY = _undeclared_secrecy()
if _MISSING_SECRECY:
    raise RuntimeError(
        "settings fields must declare secrecy via setting()/credential():"
        f" {_MISSING_SECRECY}"
    )


def engine_class(kind: EngineKind) -> type[Engine]:
    return ENGINE_CLASSES[kind]


def build_engine(config: ResolvedEngine) -> Engine:
    return engine_class(config.kind)(config)


def capabilities_for(config: ResolvedEngine) -> EngineCapabilities:
    """Capabilities from config alone — used to describe disabled engines
    (which are never instantiated) in the /engines listing."""
    return engine_class(config.kind).describe(config)


def credential_fields(kind: EngineKind) -> list[CredentialField]:
    """The credentials a provider of ``kind`` needs, so the availability gate
    and the dashboard's credential form both read one declaration."""
    return engine_class(kind).credentials()


def provider_settings_model(kind: EngineKind) -> type[ProviderSettings]:
    return engine_class(kind).PROVIDER_SETTINGS


def engine_settings_model(kind: EngineKind) -> type[EngineSettings]:
    return engine_class(kind).ENGINE_SETTINGS


def secret_keys(model: type[Settings]) -> set[str]:
    """Declared fields of ``model`` that hold secrets."""
    return {
        name for name in model.model_fields if field_flag(model, name, "secret") is True
    }


# -- resolution ----------------------------------------------------------------


def resolve(config: AppConfig, engine_id: str) -> ResolvedEngine | None:
    """Join an engine with its provider, validating both settings bags."""
    engine = config.engine(engine_id)
    if engine is None:
        return None
    provider = config.provider(engine.provider)
    assert provider is not None  # AppConfig validates the reference
    cls = engine_class(provider.kind)
    return ResolvedEngine(
        id=engine.id,
        provider_id=provider.id,
        kind=provider.kind,
        enabled=engine.enabled,
        provider_settings=cls.PROVIDER_SETTINGS.model_validate(provider.settings),
        engine_settings=cls.ENGINE_SETTINGS.model_validate(engine.settings),
    )


def resolve_all(config: AppConfig) -> list[ResolvedEngine]:
    resolved = [resolve(config, e.id) for e in config.engines]
    return [r for r in resolved if r is not None]


# -- validation ----------------------------------------------------------------


def validate_config(config: AppConfig) -> None:
    """Validate every settings bag against the model its kind declares.

    The config layer stores ``settings`` as an opaque dict because it may not
    import this package, so this is where a kind's own rules are enforced.
    ``ConfigStore`` runs it for every config that becomes live.
    """
    for provider in config.providers:
        _check(
            provider_settings_model(provider.kind),
            provider.settings,
            f"provider {provider.id!r} ({provider.kind})",
        )
    for engine in config.engines:
        owner = config.provider(engine.provider)
        assert owner is not None  # AppConfig validates the reference
        _check(
            engine_settings_model(owner.kind),
            engine.settings,
            f"engine {engine.id!r} ({owner.kind})",
        )


def _check(model: type[Settings], settings: dict[str, Any], what: str) -> None:
    try:
        model.model_validate(settings)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "settings"
        raise ValueError(f"{what}: settings.{location}: {first.get('msg')}") from exc


# -- availability --------------------------------------------------------------


def is_configured(resolved: ResolvedEngine) -> bool:
    """Whether every required credential for this engine's kind is set."""
    if not resolved.provider_settings.requires_key:
        return True
    values = resolved.provider_settings.model_dump()
    return all(
        values.get(field.key)
        for field in credential_fields(resolved.kind)
        if field.required
    )


def is_available(resolved: ResolvedEngine) -> bool:
    """Enabled in config and fully configured — safe to build and route to."""
    return resolved.enabled and is_configured(resolved)
