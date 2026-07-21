"""Translation engine implementations.

Engine instantiation lands with the concrete implementations; until then
:func:`capabilities_for` lets the API report per-kind capabilities from
config alone.
"""

from ..config import EngineConfig
from .base import (
    Engine,
    EngineCapabilities,
    EngineError,
    EngineStatus,
    ErrorKind,
    HtmlResult,
    HtmlSupport,
)

__all__ = [
    "Engine",
    "EngineCapabilities",
    "EngineError",
    "EngineStatus",
    "ErrorKind",
    "HtmlResult",
    "HtmlSupport",
    "capabilities_for",
]


def capabilities_for(config: EngineConfig) -> EngineCapabilities:
    if config.kind == "deepl":
        return EngineCapabilities(html=HtmlSupport.NATIVE, glossary=True)
    return EngineCapabilities(
        html=HtmlSupport.PROMPT,
        glossary=True,
        max_input_tokens=config.max_input_tokens,
    )
