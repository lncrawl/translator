"""Write-only handling of credentials stored in config.

Secrets can be *set* through the API and the web UI, but never read back:
every response that carries config replaces each stored secret with
``SECRET_PLACEHOLDER``. Writes may send the placeholder back to mean "keep the
stored value", so a redacted config round-trips safely through ``GET /config``
→ edit → ``PUT /config`` without ever exposing a token.

Which ``settings`` keys count as secret comes from the per-kind settings models
(fields declared with ``secret=True``). A key the kind does not declare is
treated as secret as well — validation normally rejects those, but redaction
must stay safe on any dict that reached us without it.

Note that a plaintext field holding opaque user data (``extra_body``) is
returned as-is; its *contents* are never scanned, so a token pasted in there is
readable through ``GET /config``.
"""

from __future__ import annotations

from typing import Any

from ..config import AppConfig, EngineConfig, EngineKind, ProviderConfig
from ..engines import engine_settings_model, provider_settings_model, secret_keys

SECRET_PLACEHOLDER = "__secret__"


def _redact(
    settings: dict[str, Any], secrets: set[str], declared: set[str]
) -> dict[str, Any]:
    return {
        key: SECRET_PLACEHOLDER
        if value and (key in secrets or key not in declared)
        else value
        for key, value in settings.items()
    }


def redact_provider(provider: ProviderConfig) -> ProviderConfig:
    """A copy of ``provider`` with every set secret replaced by the
    placeholder. Unset secrets stay as-is so clients can still tell
    "configured" from "missing"."""
    model = provider_settings_model(provider.kind)
    return provider.model_copy(
        update={
            "settings": _redact(
                provider.settings,
                secret_keys(model),
                set(model.model_fields),
            )
        }
    )


def redact_engine(engine: EngineConfig, kind: EngineKind) -> EngineConfig:
    """The same for an engine's settings, which may also declare secrets."""
    model = engine_settings_model(kind)
    return engine.model_copy(
        update={
            "settings": _redact(
                engine.settings,
                secret_keys(model),
                set(model.model_fields),
            )
        }
    )


def redact_config(config: AppConfig) -> AppConfig:
    """A copy of ``config`` safe to serialize into any response."""
    kinds = {p.id: p.kind for p in config.providers}
    return config.model_copy(
        update={
            "providers": [redact_provider(p) for p in config.providers],
            "engines": [
                redact_engine(e, kinds[e.provider]) if e.provider in kinds else e
                for e in config.engines
            ],
        }
    )


def resolve_settings_secrets(
    entry: dict[str, Any], stored: dict[str, Any] | None
) -> dict[str, Any]:
    """Resolve placeholder values in an incoming entry against what is stored:
    placeholder means "keep what is stored". A placeholder with nothing behind
    it is dropped rather than saved literally, so the sentinel can never become
    a credential.

    Deliberately kind-blind — it only asks whether a value *is* the sentinel.
    A single ``PUT /config`` can change a provider's ``kind`` while carrying
    placeholders, and there would be no right answer to whose declarations
    apply.
    """
    resolved = dict(entry)
    settings = resolved.get("settings")
    if not isinstance(settings, dict):
        return resolved
    kept: dict[str, Any] = {}
    for key, value in settings.items():
        if value == SECRET_PLACEHOLDER:
            value = (stored or {}).get(key)
            if value is None:
                continue
        kept[key] = value
    resolved["settings"] = kept
    return resolved


def resolve_provider_secrets(
    entry: dict[str, Any], stored: ProviderConfig | None
) -> dict[str, Any]:
    return resolve_settings_secrets(entry, stored.settings if stored else None)


def resolve_engine_secrets(
    entry: dict[str, Any], stored: EngineConfig | None
) -> dict[str, Any]:
    return resolve_settings_secrets(entry, stored.settings if stored else None)


def resolve_config_secrets(candidate: AppConfig, current: AppConfig) -> AppConfig:
    """Resolve placeholders throughout an incoming full config (matching
    entries by id against ``current``)."""
    providers = [
        ProviderConfig.model_validate(
            resolve_provider_secrets(p.model_dump(), current.provider(p.id))
        )
        for p in candidate.providers
    ]
    engines = [
        EngineConfig.model_validate(
            resolve_engine_secrets(e.model_dump(), current.engine(e.id))
        )
        for e in candidate.engines
    ]
    return candidate.model_copy(update={"providers": providers, "engines": engines})
