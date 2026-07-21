"""Engine routing: lanes, client-side rate limiting, retries, and fallback."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar

from .config import AppConfig, EngineConfig
from .detect import detect_language
from .engines.base import Engine, EngineError, EngineStatus, ErrorKind, HtmlSupport
from .errors import ApiError
from .html_tools import chunk_html, strip_text, translate_html_via_segments
from .prompts import filter_glossary
from .schemas import (
    HtmlContext,
    TranslateHtmlRequest,
    TranslateHtmlResponse,
    TranslateTextRequest,
    TranslateTextResponse,
)

logger = logging.getLogger(__name__)

TaskKind = Literal["chapter", "short_text"]

_DEFAULT_QUOTA_RESET_SECONDS = 3600
_DEFAULT_CONTEXT_TOKENS = 32_000
# Fraction of an engine's context budget a single source chunk may occupy
# (the rest is for the prompt scaffold and the translated output).
_SOURCE_BUDGET_FRACTION = 0.3

T = TypeVar("T")


@dataclass
class _Runtime:
    engine: Engine
    config: EngineConfig
    semaphore: asyncio.Semaphore
    min_interval: float
    rate_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_allowed: float = 0.0
    quota_resets_at: datetime | None = None
    last_error: str | None = None

    def status(self, now: datetime) -> EngineStatus:
        if self.quota_resets_at and now < self.quota_resets_at:
            return EngineStatus.QUOTA_EXHAUSTED
        return EngineStatus.OK

    async def throttle(self) -> None:
        async with self.rate_lock:
            now = time.monotonic()
            wait = self.next_allowed - now
            self.next_allowed = max(now, self.next_allowed) + self.min_interval
        if wait > 0:
            await asyncio.sleep(wait)


def _min_interval(config: EngineConfig) -> float:
    if config.rps:
        return 1.0 / config.rps
    if config.rpm:
        return 60.0 / config.rpm
    return 0.0


class Router:
    def __init__(
        self,
        engines: list[Engine],
        config: AppConfig,
        *,
        transient_retries: int = 2,
        backoff_base_seconds: float = 2.0,
    ) -> None:
        self._config = config
        self._transient_retries = transient_retries
        self._backoff_base = backoff_base_seconds
        self._runtimes: dict[str, _Runtime] = {}
        for engine in engines:
            engine_config = config.engine(engine.id)
            assert engine_config is not None
            self._runtimes[engine.id] = _Runtime(
                engine=engine,
                config=engine_config,
                semaphore=asyncio.Semaphore(engine_config.max_concurrency),
                min_interval=_min_interval(engine_config),
            )

    def status(self, engine_id: str) -> EngineStatus | None:
        runtime = self._runtimes.get(engine_id)
        if runtime is None:
            return None
        return runtime.status(datetime.now(UTC))

    def quota_resets_at(self, engine_id: str) -> datetime | None:
        runtime = self._runtimes.get(engine_id)
        return runtime.quota_resets_at if runtime else None

    async def close(self) -> None:
        for runtime in self._runtimes.values():
            await runtime.engine.close()

    # -- candidate selection ------------------------------------------------

    def _candidates(self, task: TaskKind, override: str | None) -> list[_Runtime]:
        if override is not None:
            runtime = self._runtimes.get(override)
            if runtime is None:
                known = self._config.engine(override)
                if known is None:
                    raise ApiError(
                        422, "unknown_engine", f"unknown engine {override!r}"
                    )
                raise ApiError(
                    503,
                    "engine_disabled",
                    f"engine {override!r} is disabled (missing api key)",
                )
            return [runtime]
        lane: list[str] = getattr(self._config.routing, task)
        runtimes = [r for r in (self._runtimes.get(i) for i in lane) if r is not None]
        if not runtimes:
            raise ApiError(
                503,
                "no_engines",
                f"no enabled engines routed for task {task!r}",
            )
        return runtimes

    async def _run(
        self,
        task: TaskKind,
        override: str | None,
        fn: Callable[[Engine], Awaitable[T]],
    ) -> tuple[T, str]:
        """Try candidates in lane order; retry transient errors per engine."""
        candidates = self._candidates(task, override)
        now = datetime.now(UTC)
        quota_blocked: list[_Runtime] = []
        last_error: EngineError | None = None

        for runtime in candidates:
            if runtime.status(now) is EngineStatus.QUOTA_EXHAUSTED:
                quota_blocked.append(runtime)
                continue
            try:
                result = await self._run_on_engine(runtime, fn)
                return result, runtime.engine.id
            except EngineError as exc:
                last_error = exc
                runtime.last_error = str(exc)
                if exc.kind is ErrorKind.QUOTA:
                    seconds = exc.retry_after_seconds or _DEFAULT_QUOTA_RESET_SECONDS
                    runtime.quota_resets_at = datetime.now(UTC) + timedelta(
                        seconds=seconds
                    )
                    quota_blocked.append(runtime)
                    logger.warning(
                        "engine %s quota exhausted: %s", runtime.engine.id, exc
                    )
                else:
                    logger.warning("engine %s failed: %s", runtime.engine.id, exc)

        if quota_blocked:
            resets = [
                r.quota_resets_at
                for r in quota_blocked
                if r.quota_resets_at is not None
            ]
            retry_after = (
                max(1, int((min(resets) - datetime.now(UTC)).total_seconds()))
                if resets
                else _DEFAULT_QUOTA_RESET_SECONDS
            )
            raise ApiError(
                503,
                "all_engines_exhausted",
                "all eligible engines are quota-exhausted",
                retry_after_seconds=retry_after,
            )
        raise ApiError(
            502,
            "engine_failure",
            f"all eligible engines failed; last error: {last_error}",
        )

    async def _run_on_engine(
        self, runtime: _Runtime, fn: Callable[[Engine], Awaitable[T]]
    ) -> T:
        attempts = 1 + self._transient_retries
        for attempt in range(attempts):
            async with runtime.semaphore:
                await runtime.throttle()
                try:
                    return await fn(runtime.engine)
                except EngineError as exc:
                    if exc.kind is not ErrorKind.TRANSIENT or attempt == attempts - 1:
                        raise
                    delay = self._backoff_base * (2**attempt)
                    logger.info(
                        "engine %s transient error (attempt %d/%d): %s",
                        runtime.engine.id,
                        attempt + 1,
                        attempts,
                        exc,
                    )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    # -- public operations ----------------------------------------------------

    async def translate_text(
        self, request: TranslateTextRequest
    ) -> TranslateTextResponse:
        source_lang, detected = self._resolve_source_lang(
            request.source_lang, "\n".join(request.texts[:20])
        )
        glossary = filter_glossary(request.glossary, request.texts)

        async def fn(engine: Engine) -> list[str]:
            return await engine.translate_segments(
                request.texts,
                source_lang=source_lang,
                target_lang=request.target_lang,
                glossary=glossary,
                context=request.context,
            )

        translations, engine_id = await self._run("short_text", request.engine, fn)
        return TranslateTextResponse(
            translations=translations,
            detected_source_lang=detected,
            engine=engine_id,
        )

    async def translate_html(
        self, request: TranslateHtmlRequest
    ) -> TranslateHtmlResponse:
        text = strip_text(request.html)
        source_lang, detected = self._resolve_source_lang(request.source_lang, text)
        glossary = filter_glossary(request.glossary, [text])

        async def fn(engine: Engine) -> tuple[str, dict[str, str], list[str]]:
            capabilities = engine.capabilities
            if capabilities.html is HtmlSupport.NONE:
                result = await translate_html_via_segments(
                    engine,
                    request.html,
                    source_lang=source_lang,
                    target_lang=request.target_lang,
                    glossary=glossary,
                )
                return result.html, result.new_terms, result.warnings

            budget = capabilities.max_input_tokens or _DEFAULT_CONTEXT_TOKENS
            max_source_tokens = engine.config.chunk_tokens or max(
                1000, int(budget * _SOURCE_BUDGET_FRACTION)
            )
            chunks = chunk_html(request.html, max_source_tokens)

            parts: list[str] = []
            new_terms: dict[str, str] = {}
            warnings: list[str] = []
            if len(chunks) > 1:
                warnings.append(f"chapter split into {len(chunks)} chunks")
            if glossary and not capabilities.glossary:
                warnings.append("glossary not applied: engine lacks glossary support")
            running_glossary = dict(glossary)
            previous_tail: str | None = (
                request.context.previous_chapter_tail if request.context else None
            )
            for chunk in chunks:
                context = HtmlContext(
                    novel_title=request.context.novel_title
                    if request.context
                    else None,
                    synopsis=request.context.synopsis if request.context else None,
                    chapter_title=(
                        request.context.chapter_title if request.context else None
                    ),
                    previous_chapter_tail=previous_tail,
                )
                result = await engine.translate_html(
                    chunk,
                    source_lang=source_lang,
                    target_lang=request.target_lang,
                    glossary=running_glossary,
                    context=context,
                    extract_terms=request.extract_terms,
                )
                parts.append(result.html)
                warnings.extend(result.warnings)
                new_terms.update(result.new_terms)
                # Later chunks see terms coined earlier and continue seamlessly.
                running_glossary.update(result.new_terms)
                previous_tail = strip_text(result.html)[-500:]
            return "".join(parts), new_terms, warnings

        (html, new_terms, warnings), engine_id = await self._run(
            "chapter", request.engine, fn
        )
        return TranslateHtmlResponse(
            html=html,
            detected_source_lang=detected,
            engine=engine_id,
            new_terms={k: v for k, v in new_terms.items() if k not in request.glossary},
            warnings=warnings,
        )

    @staticmethod
    def _resolve_source_lang(
        requested: str | None, sample: str
    ) -> tuple[str | None, str | None]:
        """Returns (lang for engines, detected lang for the response)."""
        if requested:
            return requested, None
        detection = detect_language(sample)
        if detection.language == "und":
            return None, None
        return detection.language, detection.language
