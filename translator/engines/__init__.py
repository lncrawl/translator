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
    from ..languages import coverage_langs

    source_langs, target_langs = coverage_langs(config)
    if config.kind in ("deepl", "bing"):
        html, glossary, max_tokens = HtmlSupport.NATIVE, False, None
    elif config.kind == "baidu":
        html, glossary, max_tokens = HtmlSupport.NONE, False, None
    else:
        html, glossary, max_tokens = HtmlSupport.PROMPT, True, config.max_input_tokens
    return EngineCapabilities(
        html=html,
        glossary=glossary,
        max_input_tokens=max_tokens,
        source_langs=source_langs,
        target_langs=target_langs,
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
    if kind == "bing":
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
