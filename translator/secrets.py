"""Write-only handling of provider credentials.

Provider secrets (``api_key`` and any secret entry in ``options``) can be
*set* through the API and the web UI, but never read back: every response
that carries provider config replaces each stored secret with
``SECRET_PLACEHOLDER``. Writes may send the placeholder back to mean
"keep the stored value", so a redacted config round-trips safely through
``GET /config`` → edit → ``PUT /config`` without ever exposing a token.

Which ``options`` entries count as secret is driven by the per-kind
credential declarations (``CredentialField.secret``); options not declared
by the kind are treated as secret too, so unknown credentials never leak.
"""

from __future__ import annotations

from typing import Any

from .config import AppConfig, EngineKind, ProviderConfig
from .engines import credential_fields

SECRET_PLACEHOLDER = "__secret__"


def _public_option_keys(kind: EngineKind) -> set[str]:
    """Option keys declared non-secret for this kind (e.g. baidu app_id).
    Everything else stored in ``options`` is redacted."""
    return {field.key for field in credential_fields(kind) if not field.secret}


def redact_provider(provider: ProviderConfig) -> ProviderConfig:
    """A copy of ``provider`` with every set secret replaced by the
    placeholder. Unset secrets stay as-is so clients can still tell
    "configured" from "missing"."""
    public = _public_option_keys(provider.kind)
    return provider.model_copy(
        update={
            "api_key": SECRET_PLACEHOLDER if provider.api_key else provider.api_key,
            "options": {
                key: value if key in public or not value else SECRET_PLACEHOLDER
                for key, value in provider.options.items()
            },
        }
    )


def redact_config(config: AppConfig) -> AppConfig:
    """A copy of ``config`` safe to serialize into any response."""
    return config.model_copy(
        update={"providers": [redact_provider(p) for p in config.providers]}
    )


def resolve_provider_secrets(
    entry: dict[str, Any], stored: ProviderConfig | None
) -> dict[str, Any]:
    """Resolve placeholder values in an incoming provider dict against the
    currently stored provider: placeholder means "keep what is stored".
    A placeholder with nothing stored behind it is dropped rather than
    saved literally, so the sentinel can never become a credential."""
    resolved = dict(entry)
    if resolved.get("api_key") == SECRET_PLACEHOLDER:
        resolved["api_key"] = stored.api_key if stored else None
    options = resolved.get("options")
    if isinstance(options, dict):
        kept: dict[str, Any] = {}
        for key, value in options.items():
            if value == SECRET_PLACEHOLDER:
                value = stored.options.get(key) if stored else None
                if value is None:
                    continue
            kept[key] = value
        resolved["options"] = kept
    return resolved


def resolve_config_secrets(candidate: AppConfig, current: AppConfig) -> AppConfig:
    """Resolve placeholders throughout an incoming full config (matching
    providers by id against ``current``)."""
    providers = [
        ProviderConfig.model_validate(
            resolve_provider_secrets(p.model_dump(), current.provider(p.id))
        )
        for p in candidate.providers
    ]
    return candidate.model_copy(update={"providers": providers})
