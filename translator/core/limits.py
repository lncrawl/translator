"""Live health and throughput state of providers and engines.

Everything the router needs to decide *whether* an engine may be used right
now: the shared per-account rate limit and concurrency pool, quota benching,
and per-engine failure cooldowns. Pure state — nothing here makes a request.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import ProviderConfig
from ..engines import Engine, EngineStatus

UTC = timezone.utc


def min_interval(config: ProviderConfig) -> float:
    """Seconds between requests implied by the provider's rate limit."""
    if config.rps:
        return 1.0 / config.rps
    if config.rpm:
        return 60.0 / config.rpm
    return 0.0


@dataclass
class ProviderRuntime:
    """Shared per-account state: every engine on the provider throttles,
    queues, and exhausts quota together."""

    config: ProviderConfig
    min_interval: float
    next_allowed: float = 0.0
    quota_resets_at: datetime | None = None
    active_requests: int = 0
    # asyncio primitives are created on first use so they bind to the loop
    # that actually runs the router: Python 3.9 binds them at construction,
    # and the embedded service builds runtimes outside its router loop.
    _semaphore: asyncio.Semaphore | None = field(default=None, repr=False)
    _rate_lock: asyncio.Lock | None = field(default=None, repr=False)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        return self._semaphore

    @property
    def rate_lock(self) -> asyncio.Lock:
        if self._rate_lock is None:
            self._rate_lock = asyncio.Lock()
        return self._rate_lock

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
class EngineRuntime:
    engine: Engine
    provider: ProviderRuntime
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
