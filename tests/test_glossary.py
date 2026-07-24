from __future__ import annotations

from translator.glossary import protect, reinject


def test_protect_and_reinject_roundtrip() -> None:
    glossary = {"萧炎": "Xiao Yan", "斗气": "Dou Qi"}
    protected, mapping = protect("萧炎 释放了 斗气", glossary)
    # Source terms are gone; single-codepoint placeholders stand in.
    assert "萧炎" not in protected
    assert "斗气" not in protected
    assert len(mapping) == 2
    # A machine engine "translates" the surrounding text but keeps placeholders.
    engine_output = protected.replace("释放了", "released")
    assert reinject(engine_output, mapping) == "Xiao Yan released Dou Qi"


def test_protect_only_terms_present_in_text() -> None:
    protected, mapping = protect(
        "just 萧炎 here", {"萧炎": "Xiao Yan", "斗气": "Dou Qi"}
    )
    assert list(mapping.values()) == ["Xiao Yan"]
    assert reinject(protected, mapping) == "just Xiao Yan here"


def test_longer_term_wins_over_substring() -> None:
    glossary = {"斗": "Dou", "斗气大陆": "Dou Qi Continent"}
    protected, mapping = protect("欢迎来到斗气大陆", glossary)
    assert reinject(protected, mapping).endswith("Dou Qi Continent")


def test_empty_glossary_is_noop() -> None:
    protected, mapping = protect("hello", {})
    assert protected == "hello"
    assert mapping == {}
