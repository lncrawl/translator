"""Translation backends.

``base`` defines the protocol every backend implements, ``http`` the shared
client and error mapping for HTTP APIs, ``registry`` the kind → class table
that everything else goes through. The facade below is the whole surface other
packages need: they never import a concrete engine module.
"""

from .base import (
    CredentialField,
    Engine,
    EngineCapabilities,
    EngineError,
    EngineSettings,
    EngineStatus,
    ErrorKind,
    HtmlResult,
    HtmlSupport,
    ProviderSettings,
    ResolvedEngine,
    Settings,
)
from .http import HttpEngine
from .registry import (
    ENGINE_CLASSES,
    build_engine,
    capabilities_for,
    credential_fields,
    engine_class,
    engine_settings_model,
    is_available,
    is_configured,
    provider_settings_model,
    resolve,
    resolve_all,
    secret_keys,
    validate_config,
)

__all__ = [
    "ENGINE_CLASSES",
    "CredentialField",
    "Engine",
    "EngineCapabilities",
    "EngineError",
    "EngineSettings",
    "EngineStatus",
    "ErrorKind",
    "HtmlResult",
    "HtmlSupport",
    "HttpEngine",
    "ProviderSettings",
    "ResolvedEngine",
    "Settings",
    "build_engine",
    "capabilities_for",
    "credential_fields",
    "engine_class",
    "engine_settings_model",
    "is_available",
    "is_configured",
    "provider_settings_model",
    "resolve",
    "resolve_all",
    "secret_keys",
    "validate_config",
]
