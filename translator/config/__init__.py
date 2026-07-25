"""Configuration: models, built-in defaults, the overlay format, and file IO.

``models`` defines the shape, ``defaults`` the built-in lineup, ``overlay`` the
sparse merge/diff against those defaults, and ``io`` reads and writes the file.
Everything callers need is re-exported here.
"""

from .defaults import DEFAULT_CONFIG
from .io import (
    CONFIG_PATH_ENV,
    DEFAULT_CONFIG_PATH,
    load_config,
    resolve_config_path,
    save_config,
)
from .models import (
    AppConfig,
    EngineConfig,
    EngineKind,
    FailurePolicy,
    ProviderConfig,
    ResolvedEngine,
    RoutingConfig,
)
from .overlay import build_overlay

__all__ = [
    "CONFIG_PATH_ENV",
    "DEFAULT_CONFIG",
    "DEFAULT_CONFIG_PATH",
    "AppConfig",
    "EngineConfig",
    "EngineKind",
    "FailurePolicy",
    "ProviderConfig",
    "ResolvedEngine",
    "RoutingConfig",
    "build_overlay",
    "load_config",
    "resolve_config_path",
    "save_config",
]
