"""Bing / Microsoft Translator engine — keyless, via the Edge auth endpoint.

`edge.microsoft.com/translate/auth` issues a short-lived bearer token (the same
one Edge's built-in page translator uses); it authorizes the public
`api.cognitive.microsofttranslator.com` translate API. No account or API key.
Native HTML handling via `textType=html`. Glossary terms are enforced with the
service's own `<mstrans:dictionary>` markup, which forces an exact translation
for a wrapped span in both text and HTML modes.

Unofficial free use of a Microsoft endpoint — a best-effort fallback lane, not
an SLA'd provider. It can change or throttle without notice.
"""

from __future__ import annotations

import asyncio
import re
import time
from html import escape
from typing import Any

import httpx

from ..config import ResolvedEngine
from ..schemas import HtmlContext
from ..text.languages import base as base_lang
from .base import EngineError, ErrorKind, HtmlResult, HtmlSupport
from .http import HttpEngine

_AUTH_URL = "https://edge.microsoft.com/translate/auth"
_TRANSLATE_URL = "https://api.cognitive.microsofttranslator.com/translate"
# Edge tokens live ~10 minutes; refresh a little early.
_TOKEN_TTL = 480.0
# MS caps a request at 50k chars across the whole array; stay well under it.
_MAX_INPUT_TOKENS = 20_000

# Microsoft Translator codes. Chinese needs a script; other languages use the
# base subtag, which matches MS's format.
_CODES = {
    "zh": "zh-Hans",
    "zh-Hans": "zh-Hans",
    "zh-Hant": "zh-Hant",
}


def lang_code(tag: str) -> str:
    """Microsoft Translator code; base subtag for anything unmapped."""
    return _CODES.get(tag) or base_lang(tag)


class BingEngine(HttpEngine):
    KIND = "bing"
    HTML = HtmlSupport.NATIVE
    READ_TIMEOUT = 120.0

    def __init__(self, config: ResolvedEngine) -> None:
        super().__init__(config)
        self._token: str = ""
        self._token_expiry: float = float("-inf")
        self._lazy_token_lock: asyncio.Lock | None = None

    @classmethod
    def max_input_tokens(cls, config: ResolvedEngine) -> int | None:
        """The service's own request cap bounds whatever config asks for."""
        return min(config.max_input_tokens or _MAX_INPUT_TOKENS, _MAX_INPUT_TOKENS)

    @property
    def _token_lock(self) -> asyncio.Lock:
        if self._lazy_token_lock is None:
            self._lazy_token_lock = asyncio.Lock()
        return self._lazy_token_lock

    @staticmethod
    def _apply_glossary(text: str, glossary: dict[str, str]) -> str:
        """Wrap glossary source terms in the service's forced-translation markup.

        A single non-overlapping pass (longest terms first) so a term already
        wrapped isn't rewrapped when a shorter term is a substring of it.
        """
        terms = sorted((src for src in glossary if src), key=len, reverse=True)
        if not terms:
            return text
        pattern = re.compile("|".join(re.escape(src) for src in terms))

        def wrap(match: re.Match[str]) -> str:
            src = match.group(0)
            dst = escape(glossary[src], quote=True)
            return f'<mstrans:dictionary translation="{dst}">{src}</mstrans:dictionary>'

        return pattern.sub(wrap, text)

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
        params: dict[str, Any] = {"api-version": "3.0", "to": lang_code(target_lang)}
        if source_lang:
            params["from"] = lang_code(source_lang)
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
            raise self.transport_error(exc) from exc
        if response.status_code != 200:
            raise self.classify_http_error(response)
        try:
            data = response.json()
            results = [str(item["translations"][0]["text"]) for item in data]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise self.malformed() from exc
        return self.expect_count(results, len(texts))

    def classify_http_error(self, response: httpx.Response) -> EngineError:
        status = response.status_code
        if status == 401:  # token expired mid-flight; drop it and retry
            self._token_expiry = float("-inf")
            return EngineError(self.detail(response), ErrorKind.TRANSIENT)
        if status == 429:
            return EngineError(self.detail(response), ErrorKind.QUOTA)
        return super().classify_http_error(response)

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
        prepared = [self._apply_glossary(s, glossary) for s in segments]
        return await self._translate(
            prepared, source_lang=source_lang, target_lang=target_lang, html=False
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
        prepared = self._apply_glossary(html, glossary)
        translated = await self._translate(
            [prepared], source_lang=source_lang, target_lang=target_lang, html=True
        )
        return HtmlResult(html=translated[0])
