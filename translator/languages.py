"""BCP 47 language tags: validation, canonical forms, and engine mappings.

The API accepts an ISO 639-1 primary subtag plus an optional ISO 15924
script or ISO 3166-1 region subtag (e.g. ``zh``, ``zh-TW``, ``zh-Hant``,
``pt-BR``). Tags are canonicalized once at the request boundary; engines
receive helpers instead of parsing tags themselves:

- :func:`base` for routing, detection, and script checks,
- :func:`display_name` for LLM prompts (models understand names, not codes),
- :func:`deepl_source_lang` / :func:`deepl_target_lang` for DeepL's enums,
- :func:`nllb_lang` for NLLB's FLORES-200 codes.
"""

from __future__ import annotations

import re

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


# FLORES-200 codes used by NLLB models. Exact tag first, then base subtag;
# unmapped languages are unsupported by the NLLB engine (it raises).
_NLLB_CODES = {
    "zh": "zho_Hans",
    "zh-Hans": "zho_Hans",
    "zh-Hant": "zho_Hant",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "en": "eng_Latn",
    "pt": "por_Latn",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "ru": "rus_Cyrl",
    "id": "ind_Latn",
    "vi": "vie_Latn",
    "th": "tha_Thai",
    "tr": "tur_Latn",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
    "pl": "pol_Latn",
    "nl": "nld_Latn",
    "uk": "ukr_Cyrl",
    "bn": "ben_Beng",
    "fa": "pes_Arab",
    "sv": "swe_Latn",
    "da": "dan_Latn",
    "no": "nob_Latn",
    "fi": "fin_Latn",
    "cs": "ces_Latn",
    "ro": "ron_Latn",
    "hu": "hun_Latn",
    "el": "ell_Grek",
    "he": "heb_Hebr",
    "bg": "bul_Cyrl",
    "sk": "slk_Latn",
    "hr": "hrv_Latn",
    "sr": "srp_Cyrl",
    "ms": "zsm_Latn",
    "tl": "tgl_Latn",
    "ur": "urd_Arab",
    "ta": "tam_Taml",
    "te": "tel_Telu",
    "ml": "mal_Mlym",
    "mr": "mar_Deva",
    "ne": "npi_Deva",
    "si": "sin_Sinh",
    "my": "mya_Mymr",
    "km": "khm_Khmr",
    "lo": "lao_Laoo",
    "mn": "khk_Cyrl",
    "az": "azj_Latn",
    "kk": "kaz_Cyrl",
    "uz": "uzn_Latn",
    "ka": "kat_Geor",
    "sw": "swh_Latn",
    "af": "afr_Latn",
    "ca": "cat_Latn",
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


def nllb_lang(tag: str) -> str | None:
    """The FLORES-200 code NLLB expects, or None when unsupported."""
    return _NLLB_CODES.get(tag) or _NLLB_CODES.get(base(tag))


def deepl_target_lang(tag: str) -> str:
    """DeepL's target enum; variants DeepL doesn't offer fall back to the
    base language (``ja-JP`` → ``JA``, not the invalid ``JA-JP``)."""
    mapped = _DEEPL_TARGETS.get(tag)
    if mapped is not None:
        return mapped
    return base(tag).upper()
