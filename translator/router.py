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
    active_requests: int = 0

    def quota_blocked(self, now: datetime) -> bool:
        return self.quota_resets_at is not None and now < self.quota_resets_at

    def has_free_slot(self) -> bool:
        """True if a concurrency slot can be taken right now without queueing.

        The event loop is single-threaded and ``Semaphore.acquire()`` on a
        free slot returns without suspending, so a caller that checks this and
        immediately enters ``async with semaphore`` cannot be raced out of it.
        """
        return not self.semaphore.locked()

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


def _pair_label(source_lang: str | None, target_lang: str) -> str:
    """A human-readable direction for error messages, e.g. 'zh->en' or
    'auto->en' when the source wasn't given or detected."""
    return f"{source_lang or 'auto'}->{target_lang}"


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

    def concurrency(self, engine_id: str) -> tuple[int, int] | None:
        """(free, total) concurrency slots for an engine's provider right now,
        or None if the engine isn't active. Slots are shared by every engine
        on the provider, so siblings report the same figures."""
        runtime = self._runtimes.get(engine_id)
        if runtime is None:
            return None
        total = runtime.provider.config.max_concurrency
        free = max(0, total - runtime.provider.active_requests)
        return free, total

    async def close(self) -> None:
        for runtime in self._runtimes.values():
            await runtime.engine.close()

    # -- candidate selection ------------------------------------------------

    def _candidates(
        self,
        task: TaskKind,
        override: str | None,
        source_lang: str | None,
        target_lang: str,
    ) -> list[_EngineRuntime]:
        pair = _pair_label(source_lang, target_lang)
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
            if not runtime.engine.supports(source_lang, target_lang):
                raise ApiError(
                    422,
                    "unsupported_language_pair",
                    f"engine {override!r} does not support {pair}",
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
        supported = [r for r in runtimes if r.engine.supports(source_lang, target_lang)]
        if not supported:
            raise ApiError(
                422,
                "unsupported_language_pair",
                f"no enabled engine supports {pair}",
            )
        return supported

    async def _run(
        self,
        task: TaskKind,
        override: str | None,
        fn: Callable[[Engine], Awaitable[T]],
        *,
        source_lang: str | None,
        target_lang: str,
    ) -> tuple[T, str]:
        """Try candidates in lane order; retry transient errors per engine.

        A busy engine (its provider's concurrency slots all taken) is skipped
        in favor of the next lane engine that can start immediately — load
        spills down the lane instead of queueing behind the top engine. Only
        if *every* eligible engine is busy do we wait, in lane order. Quota
        errors bench the whole provider until its reset; repeated failures of
        any other kind bench the engine for a cooldown period.
        """
        candidates = self._candidates(task, override, source_lang, target_lang)
        blocked: list[_EngineRuntime] = []
        deferred: list[_EngineRuntime] = []
        last_error: EngineError | None = None

        async def attempt(runtime: _EngineRuntime) -> tuple[T, str] | None:
            nonlocal last_error
            try:
                result = await self._run_on_engine(runtime, fn)
            except EngineError as exc:
                last_error = exc
                runtime.last_error = str(exc)
                if self._note_failure(runtime, exc):
                    blocked.append(runtime)
                return None
            runtime.consecutive_failures = 0
            runtime.cooldown_until = None
            return result, runtime.engine.id

        # Pass 1: eligible engines that can start right now, in lane order.
        for runtime in candidates:
            if runtime.status(datetime.now(UTC)) is not EngineStatus.OK:
                blocked.append(runtime)
            elif not runtime.provider.has_free_slot():
                deferred.append(runtime)  # busy — try a free engine first
            elif (outcome := await attempt(runtime)) is not None:
                return outcome

        # Pass 2: every eligible engine was busy — wait on them in lane order.
        for runtime in deferred:
            if runtime.status(datetime.now(UTC)) is not EngineStatus.OK:
                blocked.append(runtime)
            elif (outcome := await attempt(runtime)) is not None:
                return outcome

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

    def _note_failure(self, runtime: _EngineRuntime, exc: EngineError) -> bool:
        """Record an engine error and apply benching. Returns True when it
        quota-benched the provider (so the caller marks it blocked)."""
        if exc.kind is ErrorKind.QUOTA:
            seconds = exc.retry_after_seconds or _DEFAULT_QUOTA_RESET_SECONDS
            runtime.provider.quota_resets_at = datetime.now(UTC) + timedelta(
                seconds=seconds
            )
            logger.warning(
                "provider %s quota exhausted (via engine %s): %s",
                runtime.provider.config.id,
                runtime.engine.id,
                exc,
            )
            return True
        runtime.consecutive_failures += 1
        if runtime.consecutive_failures >= self._failure_threshold:
            runtime.cooldown_until = datetime.now(UTC) + timedelta(
                seconds=self._cooldown_seconds
            )
            logger.warning(
                "engine %s benched for %.0fs after %d consecutive failures: %s",
                runtime.engine.id,
                self._cooldown_seconds,
                runtime.consecutive_failures,
                exc,
            )
        else:
            logger.warning("engine %s failed: %s", runtime.engine.id, exc)
        return False

    async def _run_on_engine(
        self, runtime: _EngineRuntime, fn: Callable[[Engine], Awaitable[T]]
    ) -> T:
        attempts = 1 + self._transient_retries
        for attempt in range(attempts):
            async with runtime.provider.semaphore:
                runtime.provider.active_requests += 1
                try:
                    await runtime.provider.throttle()
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
                finally:
                    runtime.provider.active_requests -= 1
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

        translations, engine_id = await self._run(
            "short_text",
            request.engine,
            fn,
            source_lang=source_lang,
            target_lang=request.target_lang,
        )
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
            "chapter",
            request.engine,
            fn,
            source_lang=source_lang,
            target_lang=request.target_lang,
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
