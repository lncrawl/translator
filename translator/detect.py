"""Local language detection: Unicode script heuristics + lingua fallback.

No network calls and no engine quota. Hangul and kana identify Korean and
Japanese near-perfectly; hanzi-only text (ambiguous between Chinese and a
kanji-only Japanese title) and everything else goes through lingua.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from bs4 import BeautifulSoup

_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]")
_KANA = re.compile(r"[぀-ヿㇰ-ㇿｦ-ﾟ]")
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

# Detection quality saturates quickly; cap work on chapter-sized inputs.
_MAX_CHARS = 4000


@dataclass(frozen=True)
class Detection:
    language: str
    confidence: float


UNKNOWN = Detection("und", 0.0)


def _strip_html(text: str) -> str:
    if "<" in text and ">" in text:
        return BeautifulSoup(text, "html.parser").get_text(" ")
    return text


@lru_cache(maxsize=1)
def _detector():  # type: ignore[no-untyped-def]
    from lingua import LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_all_languages().with_low_accuracy_mode().build()


def _lingua_detect(text: str) -> Detection:
    values = _detector().compute_language_confidence_values(text)
    if not values:
        return UNKNOWN
    best = values[0]
    code = best.language.iso_code_639_1.name.lower()
    return Detection(code, round(float(best.value), 4))


def detect_language(text: str) -> Detection:
    plain = _strip_html(text)[:_MAX_CHARS].strip()
    if not plain:
        return UNKNOWN

    hangul = len(_HANGUL.findall(plain))
    kana = len(_KANA.findall(plain))
    han = len(_HAN.findall(plain))
    cjk = hangul + kana + han

    if cjk:
        # Any meaningful kana presence means Japanese: Chinese and Korean
        # text never mixes kana in, while Japanese prose is mostly kana+kanji.
        if kana >= 2 or (kana >= 1 and han >= 1):
            return Detection("ja", min(0.99, 0.8 + 0.05 * kana))
        if hangul > 0 and hangul >= han:
            return Detection("ko", min(0.99, 0.8 + 0.02 * hangul))
        # Hanzi-only: statistically Chinese, but a kanji-only Japanese title
        # is indistinguishable — report zh with honest, size-scaled confidence.
        if han > 0 and han >= hangul:
            return Detection("zh", min(0.95, 0.6 + 0.01 * han))

    return _lingua_detect(plain)
