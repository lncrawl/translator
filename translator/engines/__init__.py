"""Translation engine implementations."""

from ..config import ResolvedEngine
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


def build_engine(config: ResolvedEngine) -> Engine:
    if config.kind == "deepl":
        from .deepl import DeepLEngine

        return DeepLEngine(config)
    if config.kind == "nllb":
        from .nllb import NllbEngine

        return NllbEngine(config)
    if config.kind == "bing":
        from .bing import BingEngine

        return BingEngine(config)
    if config.kind == "baidu":
        from .baidu import BaiduEngine

        return BaiduEngine(config)
    from .openai_compat import OpenAICompatEngine

    return OpenAICompatEngine(config)


def capabilities_for(config: ResolvedEngine) -> EngineCapabilities:
    """Capabilities from config alone — used to describe disabled engines
    (which are never instantiated) in the /engines listing."""
    if config.kind == "deepl":
        return EngineCapabilities(html=HtmlSupport.NATIVE, glossary=False)
    if config.kind == "nllb":
        return EngineCapabilities(html=HtmlSupport.NONE, glossary=False)
    if config.kind == "bing":
        return EngineCapabilities(html=HtmlSupport.NATIVE, glossary=False)
    if config.kind == "baidu":
        return EngineCapabilities(html=HtmlSupport.NONE, glossary=False)
    return EngineCapabilities(
        html=HtmlSupport.PROMPT,
        glossary=True,
        max_input_tokens=config.max_input_tokens,
    )
