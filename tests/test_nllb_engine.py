"""NLLB engine tests with a faked CTranslate2 translator + tokenizer."""

from types import SimpleNamespace
from typing import Any

import pytest
from helpers import make_resolved

from translator.engines.base import EngineError, ErrorKind, HtmlSupport
from translator.engines.nllb import DEFAULT_MODEL, NllbEngine, _split_sentences


class FakeSP:
    """Whitespace 'sentencepiece': one token per word."""

    def encode(self, text: str, out_type: type = str) -> list[str]:
        return text.split()

    def decode(self, tokens: list[str]) -> str:
        return " ".join(tokens)


class FakeTranslator:
    """Echoes tokens uppercased; records every batch it receives."""

    def __init__(self) -> None:
        self.batches: list[list[list[str]]] = []
        self.prefixes: list[list[list[str]]] = []

    def translate_batch(
        self,
        batch: list[list[str]],
        *,
        target_prefix: list[list[str]],
        **_: Any,
    ) -> list[Any]:
        self.batches.append(batch)
        self.prefixes.append(target_prefix)
        results = []
        for tokens, prefix in zip(batch, target_prefix, strict=True):
            body = [t.upper() for t in tokens[1:-1]]  # drop src code + </s>
            results.append(SimpleNamespace(hypotheses=[[prefix[0], *body, "</s>"]]))
        return results


def make_engine(**kwargs: Any) -> NllbEngine:
    engine = NllbEngine(make_resolved("nllb", kind="nllb", base_url=None, **kwargs))
    engine._sp = FakeSP()
    engine._translator = FakeTranslator()
    return engine


async def test_translates_segments_with_flores_codes() -> None:
    engine = make_engine()
    result = await engine.translate_segments(
        ["ni hao", "zai jian"], source_lang="zh", target_lang="en", glossary={}
    )
    assert result == ["NI HAO", "ZAI JIAN"]
    fake = engine._translator
    assert fake.batches[0][0][0] == "zho_Hans"
    assert fake.batches[0][0][-1] == "</s>"
    assert fake.prefixes[0][0] == ["eng_Latn"]


async def test_unsupported_language_is_fatal() -> None:
    engine = make_engine()
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="xx", target_lang="en", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.FATAL


async def test_missing_source_language_is_fatal() -> None:
    engine = make_engine()
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang=None, target_lang="en", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.FATAL


async def test_empty_segments_pass_through() -> None:
    engine = make_engine()
    result = await engine.translate_segments(
        ["hello", "", "  "], source_lang="ja", target_lang="en", glossary={}
    )
    assert result == ["HELLO", "", "  "]


async def test_long_segment_splits_and_rejoins() -> None:
    engine = make_engine()
    # Two sentences, each far beyond the packing budget of one unit only
    # when combined — force a split by exceeding the budget.
    first = "a " * 300
    second = "b " * 300
    result = await engine.translate_segments(
        [f"{first.strip()}. {second.strip()}."],
        source_lang="zh",
        target_lang="en",
        glossary={},
    )
    assert len(result) == 1
    assert "A" in result[0] and "B" in result[0]
    # The single segment was packed into more than one translation unit.
    assert len(engine._translator.batches[0]) > 1


async def test_capabilities_and_default_model() -> None:
    engine = make_engine()
    assert engine.capabilities.html is HtmlSupport.NONE
    assert engine.capabilities.glossary is False
    assert engine._model_spec == DEFAULT_MODEL
    assert make_engine(model="some/repo")._model_spec == "some/repo"


async def test_beam_size_from_extra_body() -> None:
    assert make_engine(extra_body={"beam_size": 5})._beam_size == 5
    assert make_engine()._beam_size >= 1


def test_split_sentences_handles_cjk_and_ascii() -> None:
    parts = _split_sentences("第一句。第二句！Third sentence. Fourth?")
    assert parts == ["第一句。", "第二句！", "Third sentence.", "Fourth?"]
    assert _split_sentences("no terminator") == ["no terminator"]


async def test_translation_failure_is_transient() -> None:
    engine = make_engine()

    class Boom:
        def translate_batch(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")

    engine._translator = Boom()
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="zh", target_lang="en", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.TRANSIENT
