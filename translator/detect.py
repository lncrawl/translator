"""Local language detection: Unicode script heuristics + langdetect fallback.

No network calls and no engine quota. Hangul and kana identify Korean and
Japanese near-perfectly; hanzi-only text (ambiguous between Chinese and a
kanji-only Japanese title) and everything else goes through langdetect.
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
def _detect_langs():  # type: ignore[no-untyped-def]
    from langdetect import DetectorFactory, detect_langs

    # langdetect is nondeterministic unless seeded.
    DetectorFactory.seed = 0
    return detect_langs


def _langdetect_detect(text: str) -> Detection:
    from langdetect.lang_detect_exception import LangDetectException

    try:
        values = _detect_langs()(text)
    except LangDetectException:
        # Raised on featureless input (digits, punctuation, emoji).
        return UNKNOWN
    if not values:
        return UNKNOWN
    best = values[0]
    # langdetect reports regional variants (zh-cn, zh-tw); keep the base code.
    code = str(best.lang).split("-")[0].lower()
    return Detection(code, round(float(best.prob), 4))


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

    return _langdetect_detect(plain)
