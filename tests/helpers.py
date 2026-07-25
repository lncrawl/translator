"""Shared test doubles."""

from __future__ import annotations

from typing import Any

from translator.config import AppConfig
from translator.engines import engine_class
from translator.engines.base import (
    Engine,
    EngineCapabilities,
    EngineSettings,
    HtmlResult,
    HtmlSupport,
    ProviderSettings,
    ResolvedEngine,
)
from translator.schemas import HtmlContext

# Enough to build an openai engine; other kinds take nothing or supply their own.
DEFAULT_PROVIDER_SETTINGS: dict[str, dict[str, Any]] = {
    "openai": {"base_url": "http://fake/v1"},
}


def make_resolved(
    engine_id: str = "test",
    *,
    kind: Any = "openai",
    provider_settings: dict[str, Any] | None = None,
    engine_settings: dict[str, Any] | None = None,
    requires_key: bool = True,
    enabled: bool = True,
) -> ResolvedEngine:
    cls = engine_class(kind)
    if provider_settings is None:
        provider_settings = dict(DEFAULT_PROVIDER_SETTINGS.get(kind, {}))
    provider_settings.setdefault("requires_key", requires_key)
    return ResolvedEngine(
        id=engine_id,
        provider_id=engine_id,
        kind=kind,
        enabled=enabled,
        provider_settings=cls.PROVIDER_SETTINGS.model_validate(provider_settings),
        engine_settings=cls.ENGINE_SETTINGS.model_validate(engine_settings or {}),
    )


class FakeEngine(Engine):
    """Deterministic engine: prefixes segments with its id, wraps HTML in
    [id]…, and raises queued exceptions first (one per call)."""

    KIND = "openai"
    HTML = HtmlSupport.PROMPT

    def __init__(
        self,
        engine_id: str,
        *,
        html_support: HtmlSupport = HtmlSupport.PROMPT,
        glossary: bool = True,
        max_input_tokens: int | None = None,
        chunk_tokens: int | None = None,
        errors: list[Exception] | None = None,
        new_terms: dict[str, str] | None = None,
        source_langs: list[str] | None = None,
        target_langs: list[str] | None = None,
    ) -> None:
        # Not an OpenAICompatEngine subclass, so the shared bases are what it
        # should carry; it declares no kind-specific settings of its own.
        super().__init__(
            ResolvedEngine(
                id=engine_id,
                provider_id=engine_id,
                kind="openai",
                enabled=True,
                provider_settings=ProviderSettings(requires_key=False),
                engine_settings=EngineSettings(
                    chunk_tokens=chunk_tokens,
                    source_langs=source_langs,
                    target_langs=target_langs,
                ),
            )
        )
        self._caps = EngineCapabilities(
            html=html_support, glossary=glossary, max_input_tokens=max_input_tokens
        )
        self._errors = list(errors or [])
        self._new_terms = dict(new_terms or {})
        self.segment_calls: list[list[str]] = []
        self.html_calls: list[str] = []

    @property
    def capabilities(self) -> EngineCapabilities:
        return self._caps

    def _maybe_fail(self) -> None:
        if self._errors:
            raise self._errors.pop(0)

    async def translate_segments(
        self,
        segments: list[str],
        *,
        source_lang: str | None,
        target_lang: str,
        glossary: dict[str, str],
        context: str | None = None,
    ) -> list[str]:
        self.segment_calls.append(list(segments))
        self._maybe_fail()
        return [f"{self.id}:{s}" for s in segments]

    async def translate_html(
        self,
        html: str,
        *,
        source_lang: str | None,
        target_lang: str,
        glossary: dict[str, str],
        context: HtmlContext | None = None,
        extract_terms: bool = True,
    ) -> HtmlResult:
        self.html_calls.append(html)
        self._maybe_fail()
        return HtmlResult(html=f"[{self.id}]{html}", new_terms=dict(self._new_terms))


def make_config(
    *engine_ids: str,
    chapter: list[str] | None = None,
    short_text: list[str] | None = None,
    extra_engines: list[dict[str, object]] | None = None,
    failure_policy: dict[str, object] | None = None,
) -> AppConfig:
    providers: list[dict[str, object]] = [
        {
            "id": i,
            "kind": "openai",
            "settings": {"base_url": "http://fake", "requires_key": False},
        }
        for i in engine_ids
    ]
    engines: list[dict[str, object]] = [{"id": i, "provider": i} for i in engine_ids]
    engines.extend(extra_engines or [])
    return AppConfig.model_validate(
        {
            "providers": providers,
            "engines": engines,
            # Tests want deterministic timing, not the production defaults.
            "failure_policy": failure_policy
            or {"transient_retries": 0, "backoff_base_seconds": 0},
            "routing": {
                "chapter": chapter if chapter is not None else list(engine_ids),
                "short_text": short_text
                if short_text is not None
                else list(engine_ids),
            },
        }
    )
