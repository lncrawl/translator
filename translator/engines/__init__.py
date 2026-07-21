"""Translation engine implementations."""

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
    "build_engine",
    "capabilities_for",
]


def build_engine(config: EngineConfig) -> Engine:
    if config.kind == "deepl":
        from .deepl import DeepLEngine

        return DeepLEngine(config)
    from .openai_compat import OpenAICompatEngine

    return OpenAICompatEngine(config)


def capabilities_for(config: EngineConfig) -> EngineCapabilities:
    """Capabilities from config alone — used to describe disabled engines
    (which are never instantiated) in the /engines listing."""
    if config.kind == "deepl":
        return EngineCapabilities(html=HtmlSupport.NATIVE, glossary=False)
    return EngineCapabilities(
        html=HtmlSupport.PROMPT,
        glossary=True,
        max_input_tokens=config.max_input_tokens,
    )
