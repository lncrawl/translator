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
