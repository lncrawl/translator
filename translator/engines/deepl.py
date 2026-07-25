"""DeepL API engine (Free or Pro key).

Native HTML handling via tag_handling=html. DeepL's own glossaries are
persistent server-side resources that don't fit a stateless per-request flow,
so terms are enforced client-side by placeholder substitution around the
request (see ``translator.text.glossary``).
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any

import httpx

from ..schemas import HtmlContext
from ..text.glossary import protect, reinject
from ..text.languages import base as base_lang
from .base import (
    EngineError,
    ErrorKind,
    HtmlResult,
    HtmlSupport,
    ProviderSettings,
    ResolvedEngine,
    credential,
    narrow,
)
from .http import HttpEngine

UTC = timezone.utc

_FREE_BASE_URL = "https://api-free.deepl.com"
_PRO_BASE_URL = "https://api.deepl.com"

# DeepL target variants (deepl.com/docs-api). Unlisted tags fall back to the
# uppercased base tag, which matches DeepL's format for plain languages.
_TARGETS = {
    "en": "EN-US",
    "en-US": "EN-US",
    "en-GB": "EN-GB",
    "pt": "PT-BR",
    "pt-BR": "PT-BR",
    "pt-PT": "PT-PT",
    "zh": "ZH-HANS",
    "zh-Hans": "ZH-HANS",
    "zh-Hant": "ZH-HANT",
}


def source_lang_code(tag: str) -> str:
    """DeepL source languages carry no variant."""
    return base_lang(tag).upper()


def target_lang_code(tag: str) -> str:
    """DeepL's target enum; variants DeepL doesn't offer fall back to the
    base language (``ja-JP`` → ``JA``, not the invalid ``JA-JP``)."""
    return _TARGETS.get(tag) or base_lang(tag).upper()


def _seconds_until_next_month() -> int:
    now = datetime.now(UTC)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    reset = datetime(now.year, now.month, days_in_month, tzinfo=UTC)
    remaining = (reset - now).total_seconds() + 86400
    return max(3600, int(remaining))


class DeepLProviderSettings(ProviderSettings):
    api_key: str | None = credential(
        "API key", secret=True, description="DeepL Free keys end in ':fx'"
    )


class DeepLEngine(HttpEngine):
    KIND = "deepl"
    HTML = HtmlSupport.NATIVE
    PROVIDER_SETTINGS = DeepLProviderSettings

    def __init__(self, config: ResolvedEngine) -> None:
        provider = narrow(config.provider_settings, DeepLProviderSettings)
        key = provider.api_key
        if not key:
            raise ValueError(f"engine {config.id!r}: deepl requires an api key")
        base_url = _FREE_BASE_URL if key.endswith(":fx") else _PRO_BASE_URL
        super().__init__(
            config,
            base_url=base_url,
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
        )

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
            "target_lang": target_lang_code(target_lang),
        }
        if source_lang:
            payload["source_lang"] = source_lang_code(source_lang)
        if html:
            payload["tag_handling"] = "html"
        try:
            response = await self._client.post("/v2/translate", json=payload)
        except httpx.HTTPError as exc:
            raise self.transport_error(exc) from exc
        if response.status_code != 200:
            raise self.classify_http_error(response)
        try:
            translations = response.json()["translations"]
            results = [str(t["text"]) for t in translations]
        except (KeyError, TypeError, ValueError) as exc:
            raise self.malformed() from exc
        return self.expect_count(results, len(texts))

    def classify_http_error(self, response: httpx.Response) -> EngineError:
        if response.status_code == 456:  # monthly character quota exceeded
            return EngineError(
                self.detail(response),
                ErrorKind.QUOTA,
                retry_after_seconds=_seconds_until_next_month(),
            )
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
        protected = [protect(s, glossary) for s in segments]
        translated = await self._translate(
            [p for p, _ in protected],
            source_lang=source_lang,
            target_lang=target_lang,
            html=False,
        )
        return [reinject(t, m) for t, (_, m) in zip(translated, protected)]

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
        protected, mapping = protect(html, glossary)
        translated = await self._translate(
            [protected],
            source_lang=source_lang,
            target_lang=target_lang,
            html=True,
        )
        return HtmlResult(html=reinject(translated[0], mapping))
