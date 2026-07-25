"""BCP 47 language tags: validation and canonical forms.

The API accepts an ISO 639-1 primary subtag plus an optional ISO 15924
script or ISO 3166-1 region subtag (e.g. ``zh``, ``zh-TW``, ``zh-Hant``,
``pt-BR``). Tags are canonicalized once at the request boundary, so everything
downstream sees one spelling per meaning:

- :func:`base` for routing, detection, and script checks,
- :func:`display_name` for LLM prompts (models understand names, not codes),
- :func:`allowed` for config language allowlists.

Provider-specific code tables (DeepL's enum, Microsoft's and Baidu's codes)
live with the engine that speaks them, not here.
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


def allowed(tag: str | None, allowlist: list[str] | None) -> bool:
    """Whether ``tag`` passes a config language allowlist (None = unrestricted).
    An unknown language against a restricted list is not allowed."""
    if allowlist is None:
        return True
    if tag is None:
        return False
    return base(tag) in {base(a) for a in allowlist}
