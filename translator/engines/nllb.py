"""Local NLLB engine via CTranslate2 (the OpenNMT inference runtime).

Runs Meta's NLLB-200 translation model in-process on CPU — no API key, no
sidecar service. The model (a pre-converted int8 CTranslate2 snapshot) is
downloaded from Hugging Face on first use and cached under the standard HF
cache dir ($HF_HOME), so set that to a persistent volume in containers.

``model`` in the engine config is a Hugging Face repo id (or a local
directory containing a CTranslate2 model + sentencepiece.bpe.model).
NLLB is a sentence-level NMT model: segments are split into sentences,
packed into token-budgeted units, and rejoined after translation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from ..config import ResolvedEngine
from ..languages import nllb_lang
from .base import (
    Engine,
    EngineCapabilities,
    EngineError,
    ErrorKind,
    HtmlSupport,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "OpenNMT/nllb-200-distilled-1.3B-ct2-int8"

_SPM_FILE = "sentencepiece.bpe.model"
# Every NLLB-200 variant shares one sentencepiece tokenizer (FLORES-200);
# some CTranslate2 conversions don't bundle it, so fall back to the
# canonical copy from Meta's smallest NLLB repo.
_SPM_FALLBACK_REPO = "facebook/nllb-200-distilled-600M"

# NLLB is trained on single sentences; long inputs degrade and CTranslate2
# truncates past its max input length. Sentences are greedily packed into
# units of at most this many source tokens.
_UNIT_TOKEN_BUDGET = 384
_DEFAULT_BEAM_SIZE = 2

# Sentence boundaries: ASCII and CJK terminators, plus newlines. Closing
# quotes/brackets stay attached to the sentence they end.
_SENTENCE_END = re.compile(r"(?<=[.!?。．！？…])[\s]+|(?<=[。．！？…])|\n+")


def _split_sentences(text: str) -> list[str]:
    parts = [p for p in _SENTENCE_END.split(text) if p and p.strip()]
    return parts or [text]


class NllbEngine(Engine):
    def __init__(self, config: ResolvedEngine) -> None:
        super().__init__(config)
        self._model_spec = config.model or DEFAULT_MODEL
        self._translator: Any = None
        self._sp: Any = None
        self._load_lock = asyncio.Lock()
        beam = config.extra_body.get("beam_size", _DEFAULT_BEAM_SIZE)
        self._beam_size = max(1, int(beam))

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(html=HtmlSupport.NONE, glossary=False)

    # -- model loading --------------------------------------------------------

    def _load_sync(self) -> None:
        model_dir = Path(self._model_spec)
        if not model_dir.is_dir():
            from huggingface_hub import snapshot_download

            logger.info(
                "%s: fetching NLLB model %s (cached after first download)",
                self.id,
                self._model_spec,
            )
            model_dir = Path(snapshot_download(self._model_spec))

        spm_path = model_dir / _SPM_FILE
        if not spm_path.exists():
            from huggingface_hub import hf_hub_download

            spm_path = Path(hf_hub_download(_SPM_FALLBACK_REPO, _SPM_FILE))

        import ctranslate2
        import sentencepiece

        self._sp = sentencepiece.SentencePieceProcessor(model_file=str(spm_path))
        self._translator = ctranslate2.Translator(str(model_dir), device="cpu")
        logger.info("%s: NLLB model loaded from %s", self.id, model_dir)

    async def _ensure_loaded(self) -> None:
        if self._translator is not None:
            return
        async with self._load_lock:
            if self._translator is not None:
                return
            try:
                await asyncio.to_thread(self._load_sync)
            except EngineError:
                raise
            except Exception as exc:
                # Usually a download hiccup; the router retries with backoff
                # and benches the engine after repeated failures.
                raise EngineError(
                    f"{self.id}: failed to load NLLB model {self._model_spec!r}: {exc}",
                    ErrorKind.TRANSIENT,
                ) from exc

    # -- translation -----------------------------------------------------------

    def _lang_code(self, tag: str | None, role: str) -> str:
        if not tag:
            raise EngineError(
                f"{self.id}: NLLB requires a {role} language and none was"
                " given or detected",
                ErrorKind.FATAL,
            )
        code = nllb_lang(tag)
        if code is None:
            raise EngineError(
                f"{self.id}: {role} language {tag!r} is not supported by NLLB",
                ErrorKind.FATAL,
            )
        return code

    def _translate_sync(
        self, units: list[list[str]], src_code: str, tgt_code: str
    ) -> list[str]:
        """Translate tokenized units; returns detokenized translations."""
        results = self._translator.translate_batch(
            [[src_code, *tokens, "</s>"] for tokens in units],
            target_prefix=[[tgt_code]] * len(units),
            beam_size=self._beam_size,
            batch_type="tokens",
            max_batch_size=1024,
        )
        translations = []
        for result in results:
            tokens = list(result.hypotheses[0])
            tokens = [t for t in tokens if t not in (tgt_code, "</s>")]
            translations.append(str(self._sp.decode(tokens)))
        return translations

    def _pack_units(self, sentences: list[str]) -> list[list[str]]:
        """Greedily pack sentence token lists into budget-sized units."""
        units: list[list[str]] = []
        current: list[str] = []
        for sentence in sentences:
            tokens = list(self._sp.encode(sentence, out_type=str))
            if not tokens:
                continue
            if current and len(current) + len(tokens) > _UNIT_TOKEN_BUDGET:
                units.append(current)
                current = []
            current.extend(tokens)
        if current:
            units.append(current)
        return units

    async def translate_segments(
        self,
        segments: list[str],
        *,
        source_lang: str | None,
        target_lang: str,
        glossary: dict[str, str],
        context: str | None = None,
    ) -> list[str]:
        src_code = self._lang_code(source_lang, "source")
        tgt_code = self._lang_code(target_lang, "target")
        await self._ensure_loaded()

        # Flatten all segments' units into one batch, remembering the span
        # of units each segment owns; empty segments pass through unchanged.
        all_units: list[list[str]] = []
        spans: list[tuple[int, int]] = []
        for segment in segments:
            units = self._pack_units(_split_sentences(segment))
            spans.append((len(all_units), len(all_units) + len(units)))
            all_units.extend(units)
        if not all_units:
            return list(segments)

        try:
            translated = await asyncio.to_thread(
                self._translate_sync, all_units, src_code, tgt_code
            )
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(
                f"{self.id}: translation failed: {exc}", ErrorKind.TRANSIENT
            ) from exc

        return [
            " ".join(translated[start:end]) if end > start else segment
            for segment, (start, end) in zip(segments, spans, strict=True)
        ]
