"""Embedded translator: a synchronous facade over the async engine router.

For host applications (threaded, sync) that want translation in-process
instead of talking to a standalone server. The service owns a dedicated
event-loop thread; every router coroutine runs there, so the router's
asyncio primitives all live on one loop no matter which thread calls in.

The dashboard/HTTP API can be mounted into the host's ASGI app via
``service.create_app()`` — it shares this service's live config and router
(``ConfigStore``), and its translate endpoints hop onto the service loop.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Coroutine, Iterable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as _FutureTimeout
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from .config import AppConfig, load_config, resolve_config_path
from .core import build_router, pipeline
from .core.store import ConfigStore
from .errors import AbortedError, InvalidRequestError
from .schemas import (
    TranslateHtmlRequest,
    TranslateHtmlResponse,
    TranslateTextRequest,
    TranslateTextResponse,
)
from .text.detect import Detection, detect_language

if TYPE_CHECKING:
    from fastapi import FastAPI

T = TypeVar("T")

# How often a signal-supervised call wakes up to poll its abort signal.
_POLL_SECONDS = 0.25
_CLOSE_TIMEOUT = 10.0

__all__ = ["AbortedError", "TranslatorService"]

M = TypeVar("M", TranslateTextRequest, TranslateHtmlRequest)


def _validate(model: type[M], request: M | dict[str, Any]) -> M:
    """Coerce a dict payload into a request model, mapping pydantic's
    ``ValidationError`` to the package's own ``InvalidRequestError`` so callers
    never import pydantic to handle bad input."""
    if not isinstance(request, dict):
        return request
    from pydantic import ValidationError

    try:
        return model.model_validate(request)
    except ValidationError as e:
        raise InvalidRequestError(str(e), errors=e.errors()) from e


class TranslatorService:
    """Sync entry point for in-process translation and language detection.

    Long-lived: construct once, ``close()`` on shutdown. All methods are
    thread-safe; concurrency, rate limits, and engine failover are handled
    by the router exactly as in the standalone server.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        config: AppConfig | None = None,
    ) -> None:
        if config is not None:
            path = Path(config_path) if config_path is not None else None
        else:
            path = resolve_config_path(config_path)
            config = load_config(path)
        self.store = ConfigStore(config, build_router(config), path)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="translator-service", daemon=True
        )
        self._thread.start()
        self.store.loop = self._loop

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # -- surface --------------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        return self.store.config

    def create_app(self, auth: bool = False) -> FastAPI:
        """The dashboard + HTTP API wired to this service's live config,
        for mounting into a host ASGI application. Set ``auth`` to declare a
        Bearer scheme so the docs show an Authorize button; the host still
        verifies the token."""
        from .server import create_app

        return create_app(store=self.store, auth=auth)

    def detect(self, texts: Iterable[str]) -> list[Detection]:
        """Local language detection; no engine quota, no event loop."""
        return [detect_language(text) for text in texts]

    def translate_text(
        self,
        request: TranslateTextRequest | dict[str, Any],
        *,
        signal: threading.Event | None = None,
        timeout: float | None = None,
    ) -> TranslateTextResponse:
        request = _validate(TranslateTextRequest, request)
        return self._call(
            pipeline.translate_text(self.store.router, request), signal, timeout
        )

    def translate_html(
        self,
        request: TranslateHtmlRequest | dict[str, Any],
        *,
        signal: threading.Event | None = None,
        timeout: float | None = None,
    ) -> TranslateHtmlResponse:
        request = _validate(TranslateHtmlRequest, request)
        return self._call(
            pipeline.translate_html(self.store.router, request), signal, timeout
        )

    def close(self) -> None:
        """Close the router's engines and stop the loop thread."""
        if self._loop.is_closed():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self.store.close(), self._loop)
            future.result(_CLOSE_TIMEOUT)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(_CLOSE_TIMEOUT)
            self._loop.close()

    # -- plumbing --------------------------------------------------------------

    def _call(
        self,
        coro: Coroutine[Any, Any, T],
        signal: threading.Event | None,
        timeout: float | None,
    ) -> T:
        """Run ``coro`` on the service loop and wait for it, waking up to
        honor the abort ``signal``; cancels the router task on abort."""
        future: Future[T] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        if signal is None and timeout is None:
            return future.result()
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            try:
                return future.result(_POLL_SECONDS)
            except _FutureTimeout:
                if signal is not None and signal.is_set():
                    future.cancel()
                    raise AbortedError("translation aborted by signal") from None
                if deadline is not None and time.monotonic() >= deadline:
                    future.cancel()
                    raise AbortedError("translation timed out") from None
