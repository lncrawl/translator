"""Translation engine implementations."""

from ..config import EngineKind, ResolvedEngine
from .base import (
    CredentialField,
    Engine,
    EngineCapabilities,
    EngineError,
    EngineStatus,
    ErrorKind,
    HtmlResult,
    HtmlSupport,
)

__all__ = [
    "CredentialField",
    "Engine",
    "EngineCapabilities",
    "EngineError",
    "EngineStatus",
    "ErrorKind",
    "HtmlResult",
    "HtmlSupport",
    "build_engine",
    "capabilities_for",
    "credential_fields",
    "is_available",
    "is_configured",
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


def credential_fields(kind: EngineKind) -> list[CredentialField]:
    """The credentials a provider of ``kind`` needs — declared on the engine
    class, surfaced here without instantiating it (parallel to capabilities)."""
    if kind == "deepl":
        from .deepl import DeepLEngine

        return DeepLEngine.CREDENTIALS
    if kind == "baidu":
        from .baidu import BaiduEngine

        return BaiduEngine.CREDENTIALS
    if kind in ("nllb", "bing"):
        return []
    from .openai_compat import OpenAICompatEngine

    return OpenAICompatEngine.CREDENTIALS


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
