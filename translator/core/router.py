"""Engine selection: lanes, client-side rate limiting, retries, and fallback.

The router answers one question — *which engine runs this call, and what
happens when it fails* — and knows nothing about translation itself. Callers
hand it a lane and a coroutine factory; it picks a candidate, throttles it,
retries transient errors, benches engines that keep failing, and falls through
the lane. The work that coroutine performs lives in ``pipeline``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Literal, TypeVar

from ..config import AppConfig
from ..engines import Engine, EngineError, EngineStatus, ErrorKind, build_engine
from ..engines import is_available as engine_is_available
from ..errors import ApiError
from .limits import UTC, EngineRuntime, ProviderRuntime, min_interval

logger = logging.getLogger(__name__)

TaskKind = Literal["chapter", "short_text"]

DEFAULT_QUOTA_RESET_SECONDS = 3600

T = TypeVar("T")


def build_router(config: AppConfig) -> Router:
    """A router over every engine in ``config`` that is enabled and keyed."""
    engines = []
    for resolved in config.resolved_engines():
        if not engine_is_available(resolved):
            logger.warning(
                "engine %s disabled: %s",
                resolved.id,
                "disabled in config"
                if not resolved.enabled
                else "no api key configured",
            )
            continue
        engines.append(build_engine(resolved))
    return Router(engines, config)


def _pair_label(source_lang: str | None, target_lang: str) -> str:
    """A human-readable direction for error messages, e.g. 'zh->en' or
    'auto->en' when the source wasn't given or detected."""
    return f"{source_lang or 'auto'}->{target_lang}"


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
        self._providers: dict[str, ProviderRuntime] = {}
        self._runtimes: dict[str, EngineRuntime] = {}
        for engine in engines:
            resolved = config.resolved(engine.id)
            assert resolved is not None
            provider_config = config.provider(resolved.provider_id)
            assert provider_config is not None
            provider = self._providers.get(provider_config.id)
            if provider is None:
                provider = ProviderRuntime(
                    config=provider_config,
                    min_interval=min_interval(provider_config),
                )
                self._providers[provider_config.id] = provider
            self._runtimes[engine.id] = EngineRuntime(engine=engine, provider=provider)

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
    ) -> list[EngineRuntime]:
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

    # -- dispatch --------------------------------------------------------------

    async def run(
        self,
        task: TaskKind,
        override: str | None,
        fn: Callable[[Engine], Awaitable[T]],
        *,
        source_lang: str | None,
        target_lang: str,
    ) -> tuple[T, str]:
        """Run ``fn`` on the first candidate that succeeds; returns its result
        and the engine id that produced it.

        Candidates are tried in lane order, with transient errors retried per
        engine. A busy engine (its provider's concurrency slots all taken) is
        skipped in favor of the next lane engine that can start immediately —
        load spills down the lane instead of queueing behind the top engine.
        Only if *every* eligible engine is busy do we wait, in lane order.
        Quota errors bench the whole provider until its reset; repeated
        failures of any other kind bench the engine for a cooldown period.
        """
        candidates = self._candidates(task, override, source_lang, target_lang)
        blocked: list[EngineRuntime] = []
        deferred: list[EngineRuntime] = []
        last_error: EngineError | None = None

        async def attempt(runtime: EngineRuntime) -> tuple[T, str] | None:
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

        raise self._exhausted(blocked, last_error)

    def _exhausted(
        self, blocked: list[EngineRuntime], last_error: EngineError | None
    ) -> ApiError:
        if blocked:
            now = datetime.now(UTC)
            resets = [r.retry_at(now) for r in blocked]
            valid = [r for r in resets if r is not None]
            retry_after = (
                max(1, int((min(valid) - now).total_seconds()))
                if valid
                else DEFAULT_QUOTA_RESET_SECONDS
            )
            return ApiError(
                503,
                "all_engines_exhausted",
                "all eligible engines are quota-exhausted or cooling down"
                " after repeated failures",
                retry_after_seconds=retry_after,
            )
        return ApiError(
            502,
            "engine_failure",
            f"all eligible engines failed; last error: {last_error}",
        )

    def _note_failure(self, runtime: EngineRuntime, exc: EngineError) -> bool:
        """Record an engine error and apply benching. Returns True when it
        quota-benched the provider (so the caller marks it blocked)."""
        if exc.kind is ErrorKind.QUOTA:
            seconds = exc.retry_after_seconds or DEFAULT_QUOTA_RESET_SECONDS
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
        self, runtime: EngineRuntime, fn: Callable[[Engine], Awaitable[T]]
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
