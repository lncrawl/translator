"""Shared test doubles."""

from __future__ import annotations

from typing import Any

from translator.config import AppConfig, ResolvedEngine
from translator.engines.base import (
    Engine,
    EngineCapabilities,
    HtmlResult,
    HtmlSupport,
)
from translator.schemas import HtmlContext


def make_resolved(
    engine_id: str = "test",
    *,
    kind: Any = "openai",
    base_url: str | None = "http://fake/v1",
    api_key: str | None = None,
    options: dict[str, str] | None = None,
    requires_key: bool = True,
    model: str | None = None,
    extra_body: dict[str, Any] | None = None,
) -> ResolvedEngine:
    return ResolvedEngine(
        id=engine_id,
        provider_id=engine_id,
        kind=kind,
        base_url=base_url,
        api_key=api_key,
        options=options or {},
        requires_key=requires_key,
        model=model,
        enabled=True,
        max_input_tokens=None,
        chunk_tokens=None,
        extra_body=extra_body or {},
    )


class FakeEngine(Engine):
    """Deterministic engine: prefixes segments with its id, wraps HTML in
    [id]…, and raises queued exceptions first (one per call)."""

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
    ) -> None:
        super().__init__(
            ResolvedEngine(
                id=engine_id,
                provider_id=engine_id,
                kind="openai",
                base_url="http://fake",
                requires_key=False,
                model=None,
                enabled=True,
                max_input_tokens=None,
                chunk_tokens=chunk_tokens,
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
) -> AppConfig:
    engines: list[dict[str, object]] = [
        {"id": i, "kind": "openai", "base_url": "http://fake", "requires_key": False}
        for i in engine_ids
    ]
    engines.extend(extra_engines or [])
    return AppConfig.model_validate(
        {
            "engines": engines,
            "routing": {
                "chapter": chapter if chapter is not None else list(engine_ids),
                "short_text": short_text
                if short_text is not None
                else list(engine_ids),
            },
        }
    )
