"""Configuration: models, built-in defaults, the overlay format, and file IO.

``models`` defines the shape, ``defaults`` the built-in lineup, ``overlay`` the
sparse merge/diff against those defaults, ``io`` reads and writes the file, and
``legacy`` holds the deletable support for older file shapes. Everything
callers need is re-exported here.

Kind-specific fields live in each entry's opaque ``settings`` dict: this layer
sits below ``engines`` and cannot import it, so ``ResolvedEngine`` and per-kind
validation belong to ``translator.engines``.
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
    LANE_NAMES,
    AppConfig,
    EngineConfig,
    EngineKind,
    FailurePolicy,
    PartialFailurePolicy,
    ProviderConfig,
    RoutingConfig,
)
from .overlay import build_overlay

__all__ = [
    "CONFIG_PATH_ENV",
    "LANE_NAMES",
    "DEFAULT_CONFIG",
    "DEFAULT_CONFIG_PATH",
    "AppConfig",
    "EngineConfig",
    "EngineKind",
    "FailurePolicy",
    "PartialFailurePolicy",
    "ProviderConfig",
    "RoutingConfig",
    "build_overlay",
    "load_config",
    "resolve_config_path",
    "save_config",
]
