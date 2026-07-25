"""Baidu Translate engine (official free API) — strong on CJK.

Credentials are the App ID + Secret Key from fanyi-api.baidu.com, kept as
provider options. Each request is signed with md5(app_id + q + salt +
secret_key).

Text-only (``html: none``): the service extracts/reinjects markup around it.
Baidu splits ``q`` on newlines and caps a request near 6000 bytes, so segments
are newline-flattened and packed into byte-budgeted batches.
"""

from __future__ import annotations

import random
from hashlib import md5
from typing import Any, ClassVar

import httpx

from ..config import ResolvedEngine
from ..text.glossary import protect, reinject
from ..text.languages import base as base_lang
from .base import CredentialField, EngineError, ErrorKind, HtmlSupport
from .http import HttpEngine

_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"
# Baidu caps a query near 6000 bytes; stay under it (CJK chars are 3 bytes).
_MAX_QUERY_BYTES = 5000

# Baidu error codes worth distinguishing from the fatal default.
_TRANSIENT_CODES = {"52001", "52002", "54003", "54005"}
_QUOTA_CODES = {"54004"}

# Baidu translate codes (machinetranslate.org/baidu); several diverge from ISO.
_CODES = {
    "ar": "ara",
    "bn": "ben",
    "de": "de",
    "en": "en",
    "es": "spa",
    "fr": "fra",
    "hi": "hin",
    "id": "ind",
    "ja": "jpn",
    "ko": "kor",
    "pt": "pt",
    "ru": "ru",
    "th": "tha",
    "tr": "tur",
    "ur": "urd",
    "vi": "vie",
    "zh": "zh",
    "zh-Hans": "zh",
    "zh-Hant": "cht",
}


def lang_code(tag: str) -> str | None:
    """Baidu translate code, or None when Baidu doesn't support the tag."""
    return _CODES.get(tag) or _CODES.get(base_lang(tag))


class BaiduEngine(HttpEngine):
    KIND = "baidu"
    HTML = HtmlSupport.NONE
    READ_TIMEOUT = 120.0
    CREDENTIALS: ClassVar[list[CredentialField]] = [
        CredentialField(
            "app_id", "App ID", secret=False, description="From fanyi-api.baidu.com"
        ),
        CredentialField(
            "secret_key", "Secret key", description="Paired with the App ID"
        ),
    ]

    def __init__(self, config: ResolvedEngine) -> None:
        app_id = config.credential("app_id")
        secret = config.credential("secret_key")
        if not app_id or not secret:
            raise ValueError(
                f"engine {config.id!r}: baidu requires 'app_id' and 'secret_key'"
            )
        super().__init__(config)
        self._app_id = app_id
        self._secret = secret

    @classmethod
    def coverage(
        cls, config: ResolvedEngine
    ) -> tuple[list[str] | None, list[str] | None]:
        """Baidu has a finite catalog; config may narrow it but not widen it."""
        catalog = sorted({base_lang(tag) for tag in _CODES})
        return config.source_langs, config.target_langs or catalog

    @classmethod
    def supports_pair(
        cls, config: ResolvedEngine, source_lang: str | None, target_lang: str
    ) -> bool:
        # Baidu auto-detects the source; only the target is constrained.
        return super().supports_pair(config, source_lang, target_lang) and (
            lang_code(target_lang) is not None
        )

    def _sign(self, query: str, salt: str) -> str:
        raw = f"{self._app_id}{query}{salt}{self._secret}"
        return md5(raw.encode("utf-8")).hexdigest()

    async def _translate_batch(self, query: str, target: str) -> list[str]:
        """Translate a newline-joined query; returns one dst per source line."""
        salt = str(random.randint(10_000, 99_999))
        params: dict[str, Any] = {
            "q": query,
            "from": "auto",
            "to": target,
            "appid": self._app_id,
            "salt": salt,
            "sign": self._sign(query, salt),
        }
        try:
            response = await self._client.post(_URL, data=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise self.transport_error(exc) from exc
        except ValueError as exc:
            raise self.malformed() from exc
        if "error_code" in data:
            raise self._classify_error(
                str(data["error_code"]), data.get("error_msg", "")
            )
        try:
            return [str(item["dst"]) for item in data["trans_result"]]
        except (KeyError, TypeError) as exc:
            raise self.malformed() from exc

    def _classify_error(self, code: str, message: str) -> EngineError:
        detail = f"{self.id}: baidu error {code}: {message}"
        if code in _QUOTA_CODES:
            return EngineError(detail, ErrorKind.QUOTA)
        if code in _TRANSIENT_CODES:
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
        target = lang_code(target_lang)
        if target is None:
            raise EngineError(
                f"{self.id}: target language {target_lang!r} is not supported by Baidu",
                ErrorKind.FATAL,
            )

        # Baidu has no dictionary; enforce glossary terms by placeholder
        # substitution around the request (placeholders survive the flattening).
        protected = [protect(s, glossary) for s in segments]
        mappings = [m for _, m in protected]

        results = [p for p, _ in protected]
        # Baidu splits q on newlines, so flatten each segment to a single line
        # and skip empties (Baidu drops blank lines, which would misalign).
        indexed = [(i, " ".join(s.split())) for i, s in enumerate(results) if s.strip()]

        batch: list[tuple[int, str]] = []
        batch_bytes = 0
        for entry in indexed:
            line_bytes = len(entry[1].encode("utf-8")) + 1
            if batch and batch_bytes + line_bytes > _MAX_QUERY_BYTES:
                await self._flush(batch, target, results)
                batch, batch_bytes = [], 0
            batch.append(entry)
            batch_bytes += line_bytes
        if batch:
            await self._flush(batch, target, results)
        return [reinject(r, m) for r, m in zip(results, mappings)]

    async def _flush(
        self, batch: list[tuple[int, str]], target: str, results: list[str]
    ) -> None:
        query = "\n".join(line for _, line in batch)
        translated = await self._translate_batch(query, target)
        if len(translated) != len(batch):
            raise EngineError(
                f"{self.id}: expected {len(batch)} lines, got {len(translated)}",
                ErrorKind.TRANSIENT,
            )
        for (index, _), dst in zip(batch, translated):
            results[index] = dst
