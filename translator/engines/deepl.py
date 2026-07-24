"""DeepL API engine (Free or Pro key).

Native HTML handling via tag_handling=html. Request-level glossaries are not
applied in v1: DeepL glossaries are persistent server-side resources, which
doesn't fit a stateless per-request flow — the router surfaces a warning when
a glossary is provided.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import ResolvedEngine
from ..languages import deepl_source_lang, deepl_target_lang
from ..schemas import HtmlContext
from .base import (
    CredentialField,
    Engine,
    EngineCapabilities,
    EngineError,
    ErrorKind,
    HtmlResult,
    HtmlSupport,
)

UTC = timezone.utc

_FREE_BASE_URL = "https://api-free.deepl.com"
_PRO_BASE_URL = "https://api.deepl.com"

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=60.0)


def _seconds_until_next_month() -> int:
    now = datetime.now(UTC)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    reset = datetime(now.year, now.month, days_in_month, tzinfo=UTC)
    remaining = (reset - now).total_seconds() + 86400
    return max(3600, int(remaining))


class DeepLEngine(Engine):
    CREDENTIALS = [
        CredentialField(
            "api_key", "API key", description="DeepL Free keys end in ':fx'"
        )
    ]

    def __init__(self, config: ResolvedEngine) -> None:
        super().__init__(config)
        key = config.api_key
        if not key:
            raise ValueError(f"engine {config.id!r}: deepl requires an api key")
        base_url = config.base_url or (
            _FREE_BASE_URL if key.endswith(":fx") else _PRO_BASE_URL
        )
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
            timeout=_TIMEOUT,
        )

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(html=HtmlSupport.NATIVE, glossary=False)

    async def close(self) -> None:
        await self._client.aclose()

    async def _translate(
        self,
        texts: list[str],
        *,
        source_lang: str | None,
        target_lang: str,
        html: bool,
    ) -> list[str]:
        payload: dict[str, Any] = {
            "text": texts,
            "target_lang": deepl_target_lang(target_lang),
        }
        if source_lang:
            payload["source_lang"] = deepl_source_lang(source_lang)
        if html:
            payload["tag_handling"] = "html"
        try:
            response = await self._client.post("/v2/translate", json=payload)
        except httpx.HTTPError as exc:
            raise EngineError(f"{self.id}: {exc}", ErrorKind.TRANSIENT) from exc
        if response.status_code != 200:
            raise self._classify_http_error(response)
        try:
            translations = response.json()["translations"]
            results = [str(t["text"]) for t in translations]
        except (KeyError, TypeError, ValueError) as exc:
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
        if status == 456:  # DeepL: monthly character quota exceeded
            return EngineError(
                detail,
                ErrorKind.QUOTA,
                retry_after_seconds=_seconds_until_next_month(),
            )
        if status == 429 or status >= 500:
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
        return await self._translate(
            segments,
            source_lang=source_lang,
            target_lang=target_lang,
            html=False,
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
            [html],
            source_lang=source_lang,
            target_lang=target_lang,
            html=True,
        )
        return HtmlResult(html=translated[0])
