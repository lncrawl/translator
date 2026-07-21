"""Engine routing: lanes, client-side rate limiting, retries, and fallback."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar

from .config import AppConfig, ProviderConfig
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
class _ProviderRuntime:
    """Shared per-account state: every engine on the provider throttles,
    queues, and exhausts quota together."""

    config: ProviderConfig
    semaphore: asyncio.Semaphore
    min_interval: float
    rate_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_allowed: float = 0.0
    quota_resets_at: datetime | None = None

    def quota_blocked(self, now: datetime) -> bool:
        return self.quota_resets_at is not None and now < self.quota_resets_at

    async def throttle(self) -> None:
        async with self.rate_lock:
            now = time.monotonic()
            wait = self.next_allowed - now
            self.next_allowed = max(now, self.next_allowed) + self.min_interval
        if wait > 0:
            await asyncio.sleep(wait)


@dataclass
class _EngineRuntime:
    engine: Engine
    provider: _ProviderRuntime
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None
    last_error: str | None = None

    def status(self, now: datetime) -> EngineStatus:
        if self.provider.quota_blocked(now):
            return EngineStatus.QUOTA_EXHAUSTED
        if self.cooldown_until and now < self.cooldown_until:
            return EngineStatus.ERROR
        return EngineStatus.OK

    def retry_at(self, now: datetime) -> datetime | None:
        """When this engine becomes eligible again, if currently blocked."""
        if self.provider.quota_blocked(now):
            return self.provider.quota_resets_at
        if self.cooldown_until and now < self.cooldown_until:
            return self.cooldown_until
        return None


def _min_interval(config: ProviderConfig) -> float:
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
        transient_retries: int | None = None,
        backoff_base_seconds: float | None = None,
    ) -> None:
        policy = config.failure_policy
        self._config = config
        self._transient_retries = (
            policy.transient_retries if transient_retries is None else transient_retries
        )
        self._backoff_base = (
            policy.backoff_base_seconds
            if backoff_base_seconds is None
            else backoff_base_seconds
        )
        self._failure_threshold = policy.failure_threshold
        self._cooldown_seconds = policy.cooldown_seconds
        self._providers: dict[str, _ProviderRuntime] = {}
        self._runtimes: dict[str, _EngineRuntime] = {}
        for engine in engines:
            resolved = config.resolved(engine.id)
            assert resolved is not None
            provider_config = config.provider(resolved.provider_id)
            assert provider_config is not None
            provider = self._providers.get(provider_config.id)
            if provider is None:
                provider = _ProviderRuntime(
                    config=provider_config,
                    semaphore=asyncio.Semaphore(provider_config.max_concurrency),
                    min_interval=_min_interval(provider_config),
                )
                self._providers[provider_config.id] = provider
            self._runtimes[engine.id] = _EngineRuntime(engine=engine, provider=provider)

    def status(self, engine_id: str) -> EngineStatus | None:
        runtime = self._runtimes.get(engine_id)
        if runtime is None:
            return None
        return runtime.status(datetime.now(UTC))

    def retry_at(self, engine_id: str) -> datetime | None:
        """When a quota-exhausted or cooling-down engine is eligible again."""
        runtime = self._runtimes.get(engine_id)
        return runtime.retry_at(datetime.now(UTC)) if runtime else None

    async def close(self) -> None:
        for runtime in self._runtimes.values():
            await runtime.engine.close()

    # -- candidate selection ------------------------------------------------

    def _candidates(self, task: TaskKind, override: str | None) -> list[_EngineRuntime]:
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
                    f"engine {override!r} is disabled"
                    " (disabled in config or missing api key)",
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
        """Try candidates in lane order; retry transient errors per engine.

        Quota errors bench the whole provider until its reset; repeated
        failures of any other kind bench the engine for a cooldown period.
        """
        candidates = self._candidates(task, override)
        now = datetime.now(UTC)
        blocked: list[_EngineRuntime] = []
        last_error: EngineError | None = None

        for runtime in candidates:
            if runtime.status(now) is not EngineStatus.OK:
                blocked.append(runtime)
                continue
            try:
                result = await self._run_on_engine(runtime, fn)
                runtime.consecutive_failures = 0
                runtime.cooldown_until = None
                return result, runtime.engine.id
            except EngineError as exc:
                last_error = exc
                runtime.last_error = str(exc)
                if exc.kind is ErrorKind.QUOTA:
                    seconds = exc.retry_after_seconds or _DEFAULT_QUOTA_RESET_SECONDS
                    runtime.provider.quota_resets_at = datetime.now(UTC) + timedelta(
                        seconds=seconds
                    )
                    blocked.append(runtime)
                    logger.warning(
                        "provider %s quota exhausted (via engine %s): %s",
                        runtime.provider.config.id,
                        runtime.engine.id,
                        exc,
                    )
                else:
                    runtime.consecutive_failures += 1
                    if runtime.consecutive_failures >= self._failure_threshold:
                        runtime.cooldown_until = datetime.now(UTC) + timedelta(
                            seconds=self._cooldown_seconds
                        )
                        logger.warning(
                            "engine %s benched for %.0fs after %d consecutive"
                            " failures: %s",
                            runtime.engine.id,
                            self._cooldown_seconds,
                            runtime.consecutive_failures,
                            exc,
                        )
                    else:
                        logger.warning("engine %s failed: %s", runtime.engine.id, exc)

        if blocked:
            now = datetime.now(UTC)
            resets = [r.retry_at(now) for r in blocked]
            valid = [r for r in resets if r is not None]
            retry_after = (
                max(1, int((min(valid) - now).total_seconds()))
                if valid
                else _DEFAULT_QUOTA_RESET_SECONDS
            )
            raise ApiError(
                503,
                "all_engines_exhausted",
                "all eligible engines are quota-exhausted or cooling down"
                " after repeated failures",
                retry_after_seconds=retry_after,
            )
        raise ApiError(
            502,
            "engine_failure",
            f"all eligible engines failed; last error: {last_error}",
        )

    async def _run_on_engine(
        self, runtime: _EngineRuntime, fn: Callable[[Engine], Awaitable[T]]
    ) -> T:
        attempts = 1 + self._transient_retries
        for attempt in range(attempts):
            async with runtime.provider.semaphore:
                await runtime.provider.throttle()
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
