from __future__ import annotations

import asyncio

import pytest
from helpers import FakeEngine, make_config

from translator.config import AppConfig
from translator.engines.base import EngineError, EngineStatus, ErrorKind, HtmlSupport
from translator.errors import ApiError
from translator.router import Router
from translator.schemas import TranslateHtmlRequest, TranslateTextRequest


def make_router(*engines: FakeEngine, config=None, retries: int = 0) -> Router:
    config = config or make_config(*(e.id for e in engines))
    return Router(
        list(engines), config, transient_retries=retries, backoff_base_seconds=0
    )


class GatedEngine(FakeEngine):
    """Holds its concurrency slot until released, so a provider can be pinned
    'busy' on demand. ``started`` fires once the slot is taken."""

    def __init__(self, engine_id: str) -> None:
        super().__init__(engine_id)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def translate_segments(self, segments, **kwargs):  # type: ignore[no-untyped-def]
        self.started.set()
        await self.release.wait()
        return await FakeEngine.translate_segments(self, segments, **kwargs)


async def test_translate_text_happy_path() -> None:
    engine = FakeEngine("a")
    router = make_router(engine)
    resp = await router.translate_text(TranslateTextRequest(texts=["你好", "世界"]))
    assert resp.translations == ["a:你好", "a:世界"]
    assert resp.engine == "a"
    assert resp.detected_source_lang == "zh"


async def test_explicit_source_lang_skips_detection() -> None:
    router = make_router(FakeEngine("a"))
    resp = await router.translate_text(
        TranslateTextRequest(texts=["hi"], source_lang="en")
    )
    assert resp.detected_source_lang is None


async def test_quota_error_falls_back_to_next_lane() -> None:
    a = FakeEngine(
        "a", errors=[EngineError("q", ErrorKind.QUOTA, retry_after_seconds=120)]
    )
    b = FakeEngine("b")
    router = make_router(a, b)
    resp = await router.translate_text(TranslateTextRequest(texts=["hi"]))
    assert resp.engine == "b"
    assert router.status("a") is EngineStatus.QUOTA_EXHAUSTED

    # The exhausted engine is skipped without being called again.
    await router.translate_text(TranslateTextRequest(texts=["hi"]))
    assert len(a.segment_calls) == 1
    assert len(b.segment_calls) == 2


async def test_busy_engine_falls_back_to_next_available() -> None:
    # a's only concurrency slot is held; the next request should spill to b
    # rather than queueing behind a.
    a = GatedEngine("a")
    b = FakeEngine("b")
    router = make_router(a, b)
    held = asyncio.create_task(
        router.translate_text(TranslateTextRequest(texts=["hi"]))
    )
    await a.started.wait()

    resp = await router.translate_text(TranslateTextRequest(texts=["yo"]))
    assert resp.engine == "b"

    a.release.set()
    assert (await held).engine == "a"


async def test_concurrency_reports_free_slots() -> None:
    a = GatedEngine("a")
    router = make_router(a)
    assert router.concurrency("a") == (1, 1)  # idle: all free

    held = asyncio.create_task(
        router.translate_text(TranslateTextRequest(texts=["hi"]))
    )
    await a.started.wait()
    assert router.concurrency("a") == (0, 1)  # one in flight

    a.release.set()
    await held
    assert router.concurrency("a") == (1, 1)  # slot returned
    assert router.concurrency("ghost") is None


async def test_all_busy_waits_in_lane_order() -> None:
    # When the only engine is busy, the request waits for it (no false 503)
    # and runs on it once the slot frees.
    a = GatedEngine("a")
    router = make_router(a)
    held = asyncio.create_task(
        router.translate_text(TranslateTextRequest(texts=["hi"]))
    )
    await a.started.wait()

    waiting = asyncio.create_task(
        router.translate_text(TranslateTextRequest(texts=["yo"]))
    )
    await asyncio.sleep(0)  # let it reach the semaphore wait
    assert not waiting.done()  # holding, not rejected

    a.release.set()
    assert (await held).engine == "a"
    assert (await waiting).engine == "a"


async def test_transient_error_retries_same_engine() -> None:
    a = FakeEngine("a", errors=[EngineError("blip", ErrorKind.TRANSIENT)])
    router = make_router(a, retries=1)
    resp = await router.translate_text(TranslateTextRequest(texts=["hi"]))
    assert resp.engine == "a"
    assert len(a.segment_calls) == 2


async def test_all_quota_exhausted_returns_503_with_retry_after() -> None:
    a = FakeEngine(
        "a", errors=[EngineError("q", ErrorKind.QUOTA, retry_after_seconds=300)]
    )
    router = make_router(a)
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(TranslateTextRequest(texts=["hi"]))
    err = excinfo.value
    assert err.status_code == 503
    assert err.code == "all_engines_exhausted"
    assert err.retry_after_seconds is not None
    assert 0 < err.retry_after_seconds <= 300


async def test_fatal_error_returns_502() -> None:
    a = FakeEngine("a", errors=[EngineError("bad key", ErrorKind.FATAL)])
    router = make_router(a)
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(TranslateTextRequest(texts=["hi"]))
    assert excinfo.value.status_code == 502
    assert excinfo.value.code == "engine_failure"


async def test_unknown_engine_override_rejected() -> None:
    router = make_router(FakeEngine("a"))
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(TranslateTextRequest(texts=["hi"], engine="ghost"))
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "unknown_engine"


async def test_disabled_engine_override_rejected() -> None:
    config = make_config(
        "a",
        extra_engines=[
            {
                "id": "off",
                "kind": "openai",
                "base_url": "http://fake",
            }
        ],
    )
    router = make_router(FakeEngine("a"), config=config)
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(TranslateTextRequest(texts=["hi"], engine="off"))
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "engine_disabled"


async def test_unsupported_lane_engine_is_skipped() -> None:
    # 'a' only handles ja; a zh->en request skips it and lands on 'b'.
    a = FakeEngine("a", source_langs=["ja"])
    b = FakeEngine("b")
    router = make_router(a, b)
    resp = await router.translate_text(
        TranslateTextRequest(texts=["你好"], source_lang="zh")
    )
    assert resp.engine == "b"
    assert a.segment_calls == []  # never dispatched to the wrong-language engine


async def test_no_engine_supports_pair_rejects_early() -> None:
    a = FakeEngine("a", source_langs=["ja"])
    b = FakeEngine("b", target_langs=["fr"])
    router = make_router(a, b)
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(
            TranslateTextRequest(texts=["你好"], source_lang="zh", target_lang="en")
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "unsupported_language_pair"
    # Rejected before any engine was called.
    assert a.segment_calls == []
    assert b.segment_calls == []


async def test_override_to_unsupported_engine_rejects() -> None:
    a = FakeEngine("a", target_langs=["en"])
    router = make_router(a)
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(
            TranslateTextRequest(texts=["hi"], target_lang="fr", engine="a")
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "unsupported_language_pair"


async def test_html_prompt_engine_passthrough() -> None:
    engine = FakeEngine("a", new_terms={"药老": "Yao Lao", "萧炎": "Xiao Yan"})
    router = make_router(engine)
    resp = await router.translate_html(
        TranslateHtmlRequest(
            html="<p>萧炎见到了药老。</p>", glossary={"萧炎": "Xiao Yan"}
        )
    )
    assert resp.html == "[a]<p>萧炎见到了药老。</p>"
    assert resp.detected_source_lang == "zh"
    # Terms already in the caller's glossary are not echoed back.
    assert resp.new_terms == {"药老": "Yao Lao"}


async def test_html_none_engine_uses_segment_pipeline() -> None:
    engine = FakeEngine("a", html_support=HtmlSupport.NONE)
    router = make_router(engine)
    resp = await router.translate_html(
        TranslateHtmlRequest(html="<p>你好</p><p>世界</p>")
    )
    assert "a:你好" in resp.html
    assert "a:世界" in resp.html
    assert resp.html.count("<p>") == 2
    assert any("segment-level" in w for w in resp.warnings)
    assert engine.html_calls == []


async def test_large_chapter_is_chunked() -> None:
    engine = FakeEngine("a", max_input_tokens=4000)
    router = make_router(engine)
    html = f"<p>{'好' * 900}</p><p>{'吗' * 900}</p>"
    resp = await router.translate_html(TranslateHtmlRequest(html=html))
    assert len(engine.html_calls) == 2
    assert resp.html == f"[a]<p>{'好' * 900}</p>[a]<p>{'吗' * 900}</p>"
    assert any("2 chunks" in w for w in resp.warnings)


async def test_chunk_tokens_overrides_default_budget() -> None:
    # Default budget would fit both paragraphs in one call; the explicit
    # chunk_tokens forces a split.
    engine = FakeEngine("a", chunk_tokens=300)
    router = make_router(engine)
    html = f"<p>{'好' * 500}</p><p>{'吗' * 500}</p>"
    resp = await router.translate_html(TranslateHtmlRequest(html=html))
    assert len(engine.html_calls) == 2
    assert any("2 chunks" in w for w in resp.warnings)


async def test_quota_error_benches_whole_provider() -> None:
    # Two models on one account: exhausting quota via one blocks the other.
    config = AppConfig.model_validate(
        {
            "providers": [{"id": "p", "kind": "openai", "base_url": "http://x"}],
            "engines": [
                {"id": "a", "provider": "p"},
                {"id": "b", "provider": "p"},
            ],
            "routing": {"chapter": ["a", "b"], "short_text": ["a", "b"]},
        }
    )
    a = FakeEngine(
        "a", errors=[EngineError("q", ErrorKind.QUOTA, retry_after_seconds=120)]
    )
    b = FakeEngine("b")
    router = Router([a, b], config, transient_retries=0, backoff_base_seconds=0)
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(TranslateTextRequest(texts=["hi"]))
    assert excinfo.value.status_code == 503
    assert b.segment_calls == []  # sibling engine never wastes the call
    assert router.status("a") is EngineStatus.QUOTA_EXHAUSTED
    assert router.status("b") is EngineStatus.QUOTA_EXHAUSTED


async def test_repeated_failures_bench_engine_for_cooldown() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [
                {"id": "a", "kind": "openai", "base_url": "http://x"},
                {"id": "b", "kind": "openai", "base_url": "http://x"},
            ],
            "engines": [
                {"id": "a", "provider": "a"},
                {"id": "b", "provider": "b"},
            ],
            "routing": {"chapter": ["a", "b"], "short_text": ["a", "b"]},
            "failure_policy": {"failure_threshold": 2, "cooldown_seconds": 60},
        }
    )
    a = FakeEngine(
        "a",
        errors=[
            EngineError("boom", ErrorKind.FATAL),
            EngineError("boom", ErrorKind.FATAL),
        ],
    )
    b = FakeEngine("b")
    router = Router([a, b], config, transient_retries=0, backoff_base_seconds=0)

    # Two failing requests reach the threshold; both fall back to b.
    for _ in range(2):
        resp = await router.translate_text(TranslateTextRequest(texts=["hi"]))
        assert resp.engine == "b"
    assert router.status("a") is EngineStatus.ERROR
    assert router.retry_at("a") is not None

    # While benched, a is skipped without being called.
    await router.translate_text(TranslateTextRequest(texts=["hi"]))
    assert len(a.segment_calls) == 2
    assert len(b.segment_calls) == 3


async def test_success_resets_failure_count() -> None:
    config = make_config("a")
    a = FakeEngine("a", errors=[EngineError("boom", ErrorKind.TRANSIENT)])
    router = Router([a], config, transient_retries=0, backoff_base_seconds=0)
    with pytest.raises(ApiError):
        await router.translate_text(TranslateTextRequest(texts=["hi"]))
    resp = await router.translate_text(TranslateTextRequest(texts=["hi"]))
    assert resp.engine == "a"
    assert router.status("a") is EngineStatus.OK


async def test_glossary_unsupported_engine_warns() -> None:
    engine = FakeEngine("a", glossary=False)
    router = make_router(engine)
    resp = await router.translate_html(
        TranslateHtmlRequest(html="<p>萧炎</p>", glossary={"萧炎": "Xiao Yan"})
    )
    assert any("glossary not applied" in w for w in resp.warnings)
