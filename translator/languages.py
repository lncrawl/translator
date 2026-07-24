"""BCP 47 language tags: validation, canonical forms, and engine mappings.

The API accepts an ISO 639-1 primary subtag plus an optional ISO 15924
script or ISO 3166-1 region subtag (e.g. ``zh``, ``zh-TW``, ``zh-Hant``,
``pt-BR``). Tags are canonicalized once at the request boundary; engines
receive helpers instead of parsing tags themselves:

- :func:`base` for routing, detection, and script checks,
- :func:`display_name` for LLM prompts (models understand names, not codes),
- :func:`deepl_source_lang` / :func:`deepl_target_lang` for DeepL's enums,
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ResolvedEngine

_TAG = re.compile(r"^([a-zA-Z]{2})(?:-([a-zA-Z]{2}|[a-zA-Z]{4}))?$")

# Region subtags that imply a script; canonicalized so every engine sees a
# single spelling per meaning.
_ALIASES = {
    "zh-CN": "zh-Hans",
    "zh-SG": "zh-Hans",
    "zh-MY": "zh-Hans",
    "zh-TW": "zh-Hant",
    "zh-HK": "zh-Hant",
    "zh-MO": "zh-Hant",
}

# English names for prompt construction. Exact tag first, then base subtag;
# unknown tags fall back to the tag itself, which LLMs usually still get.
_NAMES = {
    "zh": "Chinese",
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "en": "English",
    "en-US": "American English",
    "en-GB": "British English",
    "pt": "Portuguese",
    "pt-BR": "Brazilian Portuguese",
    "pt-PT": "European Portuguese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ru": "Russian",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "tr": "Turkish",
    "ar": "Arabic",
    "hi": "Hindi",
    "pl": "Polish",
    "nl": "Dutch",
    "uk": "Ukrainian",
}

# DeepL target variants (deepl.com/docs-api). Unlisted tags fall back to the
# uppercased tag, which matches DeepL's format for plain languages.
_DEEPL_TARGETS = {
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


def canonicalize(tag: str) -> str:
    """Validate and normalize a BCP 47 tag; raises ValueError when invalid.

    Case is normalized per BCP 47 (``zh-hant`` → ``zh-Hant``, ``pt-br`` →
    ``pt-BR``) and region aliases collapse to their script form
    (``zh-TW`` → ``zh-Hant``).
    """
    match = _TAG.match(tag.strip())
    if not match:
        raise ValueError(
            "must be an ISO 639-1 code with an optional script/region"
            " subtag, e.g. 'zh', 'zh-Hant', or 'pt-BR'"
        )
    lang, subtag = match.group(1).lower(), match.group(2)
    if subtag is None:
        return lang
    subtag = subtag.upper() if len(subtag) == 2 else subtag.title()
    return _ALIASES.get(f"{lang}-{subtag}", f"{lang}-{subtag}")


def base(tag: str) -> str:
    """The ISO 639-1 primary subtag: ``zh-Hant`` → ``zh``."""
    return tag.split("-", 1)[0].lower()


def display_name(tag: str | None) -> str:
    if not tag:
        return "the source language"
    return _NAMES.get(tag) or _NAMES.get(base(tag)) or tag


def deepl_source_lang(tag: str) -> str:
    """DeepL source languages carry no variant."""
    return base(tag).upper()


def deepl_target_lang(tag: str) -> str:
    """DeepL's target enum; variants DeepL doesn't offer fall back to the
    base language (``ja-JP`` → ``JA``, not the invalid ``JA-JP``)."""
    mapped = _DEEPL_TARGETS.get(tag)
    if mapped is not None:
        return mapped
    return base(tag).upper()


# Microsoft Translator codes (keyless Bing engine). Chinese needs a script;
# other languages use the base subtag, which matches MS's format.
_BING = {
    "zh": "zh-Hans",
    "zh-Hans": "zh-Hans",
    "zh-Hant": "zh-Hant",
}

# Baidu translate codes (machinetranslate.org/baidu); several diverge from ISO.
_BAIDU = {
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


def bing_lang(tag: str) -> str:
    """Microsoft Translator code; base subtag for anything unmapped."""
    return _BING.get(tag) or base(tag)


def baidu_lang(tag: str) -> str | None:
    """Baidu translate code, or None when Baidu doesn't support the tag."""
    return _BAIDU.get(tag) or _BAIDU.get(base(tag))


def _allowed(tag: str | None, allow: list[str] | None) -> bool:
    """Whether ``tag`` passes a config language allowlist (None = unrestricted).
    An unknown language against a restricted list is not allowed."""
    if allow is None:
        return True
    if tag is None:
        return False
    return base(tag) in {base(a) for a in allow}


def supports_pair(engine: ResolvedEngine, source: str | None, target: str) -> bool:
    """Whether ``engine`` can translate this pair, without dispatching.

    Config allowlists (``source_langs``/``target_langs``) apply to every kind;
    on top of them each kind's intrinsic coverage decides. LLM, DeepL and Bing
    lanes are broad (they accept any pair and degrade gracefully); Baidu has a
    finite catalog and rejects the rest early.
    """
    if not _allowed(source, engine.source_langs):
        return False
    if not _allowed(target, engine.target_langs):
        return False
    if engine.kind == "baidu":
        # Baidu auto-detects the source; only the target is constrained.
        return baidu_lang(target) is not None
    return True


def coverage_langs(
    engine: ResolvedEngine,
) -> tuple[list[str] | None, list[str] | None]:
    """(source, target) base languages an engine covers, for the /engines
    listing. ``None`` means unrestricted. Config allowlists win; otherwise the
    kind's intrinsic catalog is described (LLM/DeepL/Bing stay unrestricted)."""

    def _from_map(mapping: Mapping[str, str]) -> list[str]:
        return sorted({base(tag) for tag in mapping})

    if engine.kind == "baidu":
        return engine.source_langs, engine.target_langs or _from_map(_BAIDU)
    return engine.source_langs, engine.target_langs
