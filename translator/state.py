"""Mutable application state: the live config and router, swapped atomically.

Config mutations build a fresh Router from the new config, swap it in, then
persist the config to the YAML file (when a path is configured) and close the
old router. In-flight requests keep the router instance they started with.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .config import AppConfig, save_config
from .engines import build_engine, is_available
from .router import Router

logger = logging.getLogger(__name__)


def build_router(config: AppConfig) -> Router:
    engines = []
    for resolved in config.resolved_engines():
        if not is_available(resolved):
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


# How long a replaced router lingers before its HTTP clients are closed, so
# in-flight translations (up to ~15 min on slow lanes) can finish on it.
RETIRED_ROUTER_GRACE_SECONDS = 900.0


class ConfigStore:
    """Holds the current config + router; serializes mutations."""

    def __init__(
        self, config: AppConfig, router: Router, path: Path | None = None
    ) -> None:
        self.config = config
        self.router = router
        self._path = path
        self._lock = asyncio.Lock()
        self._retired: set[asyncio.Task[None]] = set()

    async def apply(self, new_config: AppConfig) -> None:
        """Swap in ``new_config`` atomically and persist it."""
        async with self._lock:
            new_router = build_router(new_config)
            old_router = self.router
            self.config = new_config
            self.router = new_router
            if self._path is not None:
                save_config(new_config, self._path)
                logger.info("config updated and saved to %s", self._path)
            else:
                logger.info("config updated (in-memory only, no config path)")
            task = asyncio.create_task(self._retire(old_router))
            self._retired.add(task)
            task.add_done_callback(self._retired.discard)

    @staticmethod
    async def _retire(router: Router) -> None:
        try:
            await asyncio.sleep(RETIRED_ROUTER_GRACE_SECONDS)
        finally:
            # Cancellation (shutdown) still closes the retired router.
            await router.close()

    async def close(self) -> None:
        """Shutdown: cancel pending retirements and close everything now."""
        for task in list(self._retired):
            task.cancel()
        await self.router.close()
