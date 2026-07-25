from __future__ import annotations

import pytest

from translator.engines.prompts import (
    build_html_messages,
    parse_html_response,
    parse_text_response,
)
from translator.schemas import HtmlContext
from translator.text.glossary import filter_glossary


def test_filter_glossary_keeps_only_present_terms() -> None:
    glossary = {"萧炎": "Xiao Yan", "药老": "Yao Lao"}
    assert filter_glossary(glossary, ["萧炎走了进来"]) == {"萧炎": "Xiao Yan"}
    assert filter_glossary({}, ["anything"]) == {}


def test_build_html_messages_carries_context_glossary_and_new_terms_contract() -> None:
    context = HtmlContext(
        novel_title="Battle Through the Heavens",
        chapter_title="Chapter 1",
        synopsis="A young genius loses his power.",
        previous_chapter_tail="…and then he vanished.",
    )
    messages = build_html_messages(
        "<p>萧炎走了进来</p>",
        source_lang="zh",
        target_lang="en",
        glossary={"萧炎": "Xiao Yan"},
        context=context,
        extract_terms=True,
    )
    system = messages[0]["content"]
    user = messages[1]["content"]
    # extract_terms=True adds the NEW_TERMS instruction with the key/value contract.
    assert "<NEW_TERMS>" in system
    assert "exactly as written in the untranslated source" in system.replace("\n", " ")
    # Context lines and the glossary are threaded into the user turn.
    assert "Battle Through the Heavens" in user
    assert "Chapter 1" in user
    assert "A young genius loses his power." in user
    assert "…and then he vanished." in user
    assert "萧炎" in user and "Xiao Yan" in user
    assert "<p>萧炎走了进来</p>" in user


def test_build_html_messages_omits_new_terms_when_extraction_off() -> None:
    messages = build_html_messages(
        "<p>hi</p>",
        source_lang="zh",
        target_lang="en",
        glossary={},
        context=None,
        extract_terms=False,
    )
    assert "<NEW_TERMS>" not in messages[0]["content"]


def test_parse_text_response_plain_and_fenced() -> None:
    assert parse_text_response('["a", "b"]', expected=2) == ["a", "b"]
    assert parse_text_response('```json\n["a", "b"]\n```', expected=2) == ["a", "b"]
    assert parse_text_response('Here you go:\n["a"]', expected=1) == ["a"]


def test_parse_text_response_count_mismatch() -> None:
    with pytest.raises(ValueError, match="expected 2"):
        parse_text_response('["only one"]', expected=2)


def test_parse_text_response_no_array() -> None:
    with pytest.raises(ValueError, match="no JSON array"):
        parse_text_response("sorry, I cannot help", expected=1)


def test_parse_html_response_with_markers() -> None:
    raw = (
        "<TRANSLATION><p>Hello</p></TRANSLATION>\n"
        '<NEW_TERMS>{"药老": "Yao Lao"}</NEW_TERMS>'
    )
    html, terms = parse_html_response(raw)
    assert html == "<p>Hello</p>"
    assert terms == {"药老": "Yao Lao"}


def test_parse_html_response_without_markers_falls_back() -> None:
    html, terms = parse_html_response("<p>Hello</p>")
    assert html == "<p>Hello</p>"
    assert terms == {}


def test_parse_html_response_bad_terms_json_is_lenient() -> None:
    raw = "<TRANSLATION><p>Hi</p></TRANSLATION><NEW_TERMS>{oops</NEW_TERMS>"
    html, terms = parse_html_response(raw)
    assert html == "<p>Hi</p>"
    assert terms == {}


def test_reasoning_blocks_stripped() -> None:
    raw = (
        "<think>Let me consider the translation...</think>\n"
        "<TRANSLATION><p>Hello</p></TRANSLATION>"
    )
    html, _ = parse_html_response(raw)
    assert html == "<p>Hello</p>"

    assert parse_text_response('<think>hmm</think>["a"]', expected=1) == ["a"]
