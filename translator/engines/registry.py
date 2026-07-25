"""The kind → implementation table.

One place maps a config ``kind`` to the class that implements it; construction,
capability description, and credential discovery all read from it, so adding a
backend means writing one class and listing it here. The module-level check
keeps the table and the ``EngineKind`` literal from drifting apart.
"""

from __future__ import annotations

from typing import get_args

from ..config import EngineKind, ResolvedEngine
from .baidu import BaiduEngine
from .base import CredentialField, Engine, EngineCapabilities
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
    return engine_class(kind).CREDENTIALS


def is_configured(resolved: ResolvedEngine) -> bool:
    """Whether every required credential for this engine's kind is set."""
    if not resolved.requires_key:
        return True
    return all(
        resolved.credential(field.key)
        for field in credential_fields(resolved.kind)
        if field.required
    )


def is_available(resolved: ResolvedEngine) -> bool:
    """Enabled in config and fully configured — safe to build and route to."""
    return resolved.enabled and is_configured(resolved)
