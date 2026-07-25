"""Shared plumbing for engines that talk to a JSON HTTP API.

Owns the one long-lived ``httpx.AsyncClient`` each engine needs and turns
transport failures, non-200 responses, and malformed payloads into
:class:`EngineError` with the right :class:`ErrorKind` — the classification the
router's retry/fallback logic keys on. Subclasses set ``READ_TIMEOUT`` and
override :meth:`classify_http_error` for provider-specific status codes.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from ..config import ResolvedEngine
from .base import Engine, EngineError, ErrorKind

# How much of an error body to keep in the message.
_DETAIL_CHARS = 300


class HttpEngine(Engine):
    # Chapter translations are slow; only the read timeout differs by kind.
    READ_TIMEOUT: ClassVar[float] = 300.0
    CONNECT_TIMEOUT: ClassVar[float] = 15.0

    def __init__(
        self,
        config: ResolvedEngine,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(config)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers or {},
            timeout=httpx.Timeout(
                connect=type(self).CONNECT_TIMEOUT,
                read=type(self).READ_TIMEOUT,
                write=60.0,
                pool=60.0,
            ),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- error mapping ---------------------------------------------------------

    def transport_error(self, exc: httpx.HTTPError) -> EngineError:
        return EngineError(f"{self.id}: {exc}", ErrorKind.TRANSIENT)

    def malformed(self, what: str = "translate response") -> EngineError:
        return EngineError(f"{self.id}: malformed {what}", ErrorKind.TRANSIENT)

    def detail(self, response: httpx.Response) -> str:
        return (
            f"{self.id}: HTTP {response.status_code}: {response.text[:_DETAIL_CHARS]}"
        )

    def classify_http_error(self, response: httpx.Response) -> EngineError:
        """Map a non-200 response to an EngineError. The default treats 429 and
        5xx as transient and everything else as fatal; kinds with meaningful
        quota or auth codes override and fall back to ``super()``."""
        status = response.status_code
        if status == 429 or status >= 500:
            return EngineError(self.detail(response), ErrorKind.TRANSIENT)
        return EngineError(self.detail(response), ErrorKind.FATAL)

    def expect_count(self, results: list[str], expected: int) -> list[str]:
        """Guard the invariant every batch API must hold: one translation per
        input, in order. A mismatch would silently misalign the caller's text."""
        if len(results) != expected:
            raise EngineError(
                f"{self.id}: expected {expected} translations, got {len(results)}",
                ErrorKind.TRANSIENT,
            )
        return results
