from __future__ import annotations

import pytest
from helpers import FakeEngine

from translator.core import pipeline
from translator.engines.base import EngineError, HtmlSupport


class MiscountingEngine(FakeEngine):
    """Returns one segment too few, like a batch API that merged strings."""

    async def translate_segments(self, segments, **kwargs):  # type: ignore[no-untyped-def]
        result = await super().translate_segments(segments, **kwargs)
        return result[:-1]


async def test_segment_count_mismatch_raises_engine_error() -> None:
    engine = MiscountingEngine("bad", html_support=HtmlSupport.NONE)
    with pytest.raises(EngineError, match="segments"):
        await pipeline.translate_via_segments(
            engine,
            "<p>hello</p><p>world</p>",
            source_lang="zh",
            target_lang="en",
            glossary={},
        )


async def test_segment_output_gains_no_document_scaffolding() -> None:
    """A chapter goes out shaped as it came in.

    ``translate_via_segments`` returns ``str(soup)``, so a lenient parser that
    wraps a fragment in ``<html><body>`` would inject that scaffolding into every
    translated chapter. lxml does exactly this; ``html.parser`` is the reason the
    round-trip is clean, and this pins it.
    """
    engine = FakeEngine("fake", html_support=HtmlSupport.NONE)
    result = await pipeline.translate_via_segments(
        engine,
        "<p>one</p><p>two</p>",
        source_lang="zh",
        target_lang="en",
        glossary={},
    )
    assert result.html == "<p>fake:one</p><p>fake:two</p>"
