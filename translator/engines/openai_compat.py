"""Engine for any OpenAI-compatible chat completions API.

Covers Z.AI, Cerebras, Mistral, Groq, OpenRouter, DeepSeek, ModelScope,
Gemini's compatibility endpoint, and a local llama.cpp server — differences
are config-only.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..config import ResolvedEngine
from ..schemas import HtmlContext
from ..text.html import count_cjk, repair_untagged_output, strip_text, tag_names
from ..text.languages import base as base_lang
from . import prompts
from .base import CredentialField, EngineError, ErrorKind, HtmlResult, HtmlSupport
from .http import HttpEngine

# A 429 asking for a short pause is throttling; a long one is quota.
_THROTTLE_CUTOFF_SECONDS = 60

# Target languages (ISO 639-1 base) where CJK output characters are expected.
_CJK_TARGETS = {"zh", "ja", "ko"}


class OpenAICompatEngine(HttpEngine):
    KIND = "openai"
    HTML = HtmlSupport.PROMPT
    READ_TIMEOUT = 900.0  # a local CPU model can take ~15 min for one chapter
    CREDENTIALS: ClassVar[list[CredentialField]] = [
        CredentialField(
            "api_key", "API key", description="Bearer token for the provider"
        )
    ]

    def __init__(self, config: ResolvedEngine) -> None:
        if not config.base_url:
            raise ValueError(f"engine {config.id!r}: openai kind requires base_url")
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        super().__init__(config, base_url=config.base_url, headers=headers)

    async def _chat(
        self, messages: list[dict[str, str]], temperature: float = 0.3
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            **self.config.extra_body,
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise self.transport_error(exc) from exc

        if response.status_code != 200:
            raise self.classify_http_error(response)
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise self.malformed("completion response") from exc
        if not content or not str(content).strip():
            raise EngineError(f"{self.id}: empty completion", ErrorKind.TRANSIENT)
        return str(content)

    def classify_http_error(self, response: httpx.Response) -> EngineError:
        status = response.status_code
        if status == 429:
            retry_after = _parse_retry_after(response)
            if retry_after is not None and retry_after <= _THROTTLE_CUTOFF_SECONDS:
                return EngineError(self.detail(response), ErrorKind.TRANSIENT)
            return EngineError(
                self.detail(response), ErrorKind.QUOTA, retry_after_seconds=retry_after
            )
        if status == 402:
            return EngineError(self.detail(response), ErrorKind.QUOTA)
        if status == 408:
            return EngineError(self.detail(response), ErrorKind.TRANSIENT)
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
        messages = prompts.build_text_messages(
            segments,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=glossary,
            context=context,
        )
        raw = await self._chat(messages)
        try:
            return prompts.parse_text_response(raw, expected=len(segments))
        except ValueError as exc:
            # A malformed reply is worth one more roll of the dice upstream.
            raise EngineError(f"{self.id}: {exc}", ErrorKind.TRANSIENT) from exc

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
        messages = prompts.build_html_messages(
            html,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=glossary,
            context=context,
            extract_terms=extract_terms,
        )
        # Small models sometimes code-switch mid-word ("re凝聚"). When any
        # CJK survives in non-CJK output, regenerate once (slightly hotter
        # for diversity) and keep the attempt that leaks least.
        check_leak = base_lang(target_lang) not in _CJK_TARGETS
        best: tuple[int, str, dict[str, str]] | None = None
        for temperature in (0.3, 0.6):
            raw = await self._chat(messages, temperature=temperature)
            translated, new_terms = prompts.parse_html_response(raw)
            if not translated.strip():
                continue
            leaked = count_cjk(strip_text(translated)) if check_leak else 0
            if best is None or leaked < best[0]:
                best = (leaked, translated, new_terms)
            if leaked == 0:
                break
        if best is None:
            raise EngineError(f"{self.id}: empty translation", ErrorKind.TRANSIENT)
        leaked, translated, new_terms = best

        warnings: list[str] = []
        if leaked > 0:
            warnings.append(
                f"{leaked} untranslated CJK characters remain in the output"
                " (after one retry)"
            )
        if tag_names(translated) != tag_names(html):
            repaired = repair_untagged_output(html, translated)
            if repaired is not None:
                translated = repaired
                warnings.append("engine returned plain text; paragraphs re-wrapped")
            else:
                warnings.append("tag structure differs from source")
        # Keys must be terms that literally occur in the source: this drops
        # already-known glossary entries and hallucinated or already-translated
        # keys (e.g. "Chaos Body": "Chaos Body") that would poison the
        # caller's glossary.
        new_terms = {
            k: v
            for k, v in new_terms.items()
            if k not in glossary and k != v and k in html
        }
        return HtmlResult(html=translated, new_terms=new_terms, warnings=warnings)


def _parse_retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(float(value)))
    except ValueError:
        return None
