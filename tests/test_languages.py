from __future__ import annotations

import pytest

from translator.languages import (
    base,
    canonicalize,
    deepl_source_lang,
    deepl_target_lang,
    display_name,
)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("zh", "zh"),
        ("ZH", "zh"),
        (" ja ", "ja"),
        ("zh-hant", "zh-Hant"),
        ("zh-TW", "zh-Hant"),  # region alias collapses to script
        ("zh-cn", "zh-Hans"),
        ("pt-br", "pt-BR"),
        ("en-gb", "en-GB"),
    ],
)
def test_canonicalize(raw: str, canonical: str) -> None:
    assert canonicalize(raw) == canonical


@pytest.mark.parametrize("bad", ["", "e", "english", "zh_CN", "zh-", "zh-Hant-TW"])
def test_canonicalize_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        canonicalize(bad)


def test_base() -> None:
    assert base("zh-Hant") == "zh"
    assert base("en") == "en"


def test_display_name() -> None:
    assert display_name("zh-Hant") == "Traditional Chinese"
    assert display_name("zh") == "Chinese"
    assert display_name("ja-JP") == "Japanese"  # falls back to base name
    assert display_name("xx-YY") == "xx-YY"  # unknown: tag itself
    assert display_name(None) == "the source language"


def test_deepl_mappings() -> None:
    assert deepl_source_lang("zh-Hant") == "ZH"
    assert deepl_target_lang("zh-Hant") == "ZH-HANT"
    assert deepl_target_lang("zh") == "ZH-HANS"
    assert deepl_target_lang("en") == "EN-US"
    assert deepl_target_lang("ja") == "JA"
    # Variants DeepL doesn't offer drop to the base language.
    assert deepl_target_lang("ja-JP") == "JA"
    assert deepl_target_lang("de-AT") == "DE"
