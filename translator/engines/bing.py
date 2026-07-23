"""Bing / Microsoft Translator engine — keyless, via the Edge auth endpoint.

`edge.microsoft.com/translate/auth` issues a short-lived bearer token (the same
one Edge's built-in page translator uses); it authorizes the public
`api.cognitive.microsofttranslator.com` translate API. No account or API key.
Native HTML handling via `textType=html`; no glossary support.

Unofficial free use of a Microsoft endpoint — a best-effort fallback lane, not
an SLA'd provider. It can change or throttle without notice.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ..config import ResolvedEngine
from ..languages import bing_lang
from ..schemas import HtmlContext
from .base import (
    Engine,
    EngineCapabilities,
    EngineError,
    ErrorKind,
    HtmlResult,
    HtmlSupport,
)

_AUTH_URL = "https://edge.microsoft.com/translate/auth"
_TRANSLATE_URL = "https://api.cognitive.microsofttranslator.com/translate"
# Edge tokens live ~10 minutes; refresh a little early.
_TOKEN_TTL = 480.0
# MS caps a request at 50k chars across the whole array; stay well under it.
_MAX_INPUT_TOKENS = 20_000

_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=60.0, pool=60.0)


class BingEngine(Engine):
    def __init__(self, config: ResolvedEngine) -> None:
        super().__init__(config)
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        self._token: str = ""
        self._token_expiry: float = float("-inf")
        self._token_lock = asyncio.Lock()

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            html=HtmlSupport.NATIVE,
            glossary=False,
            max_input_tokens=_MAX_INPUT_TOKENS,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _auth_token(self) -> str:
        if time.monotonic() < self._token_expiry:
            return self._token
        async with self._token_lock:
            if time.monotonic() < self._token_expiry:
                return self._token
            try:
                response = await self._client.get(_AUTH_URL)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise EngineError(
                    f"{self.id}: auth failed: {exc}", ErrorKind.TRANSIENT
                ) from exc
            self._token = response.text.strip()
            self._token_expiry = time.monotonic() + _TOKEN_TTL
            return self._token

    async def _translate(
        self,
        texts: list[str],
        *,
        source_lang: str | None,
        target_lang: str,
        html: bool,
    ) -> list[str]:
        params: dict[str, Any] = {"api-version": "3.0", "to": bing_lang(target_lang)}
        if source_lang:
            params["from"] = bing_lang(source_lang)
        if html:
            params["textType"] = "html"
        token = await self._auth_token()
        try:
            response = await self._client.post(
                _TRANSLATE_URL,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                json=[{"Text": t} for t in texts],
            )
        except httpx.HTTPError as exc:
            raise EngineError(f"{self.id}: {exc}", ErrorKind.TRANSIENT) from exc
        if response.status_code != 200:
            raise self._classify_http_error(response)
        try:
            data = response.json()
            results = [str(item["translations"][0]["text"]) for item in data]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise EngineError(
                f"{self.id}: malformed translate response", ErrorKind.TRANSIENT
            ) from exc
        if len(results) != len(texts):
            raise EngineError(
                f"{self.id}: expected {len(texts)} translations, got {len(results)}",
                ErrorKind.TRANSIENT,
            )
        return results

    def _classify_http_error(self, response: httpx.Response) -> EngineError:
        status = response.status_code
        detail = f"{self.id}: HTTP {status}: {response.text[:300]}"
        if status == 401:  # token expired mid-flight; drop it and retry
            self._token_expiry = float("-inf")
            return EngineError(detail, ErrorKind.TRANSIENT)
        if status == 429:
            return EngineError(detail, ErrorKind.QUOTA)
        if status >= 500:
            return EngineError(detail, ErrorKind.TRANSIENT)
        return EngineError(detail, ErrorKind.FATAL)

    async def translate_segments(
        self,
        segments: list[str],
        *,
        source_lang: str | None,
        target_lang: str,
        glossary: dict[str, str],
        context: str | None = None,
    ) -> list[str]:
        if not segments:
            return []
        return await self._translate(
            segments, source_lang=source_lang, target_lang=target_lang, html=False
        )

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
        translated = await self._translate(
            [html], source_lang=source_lang, target_lang=target_lang, html=True
        )
        return HtmlResult(html=translated[0])
