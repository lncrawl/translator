import pytest
from helpers import FakeEngine, make_config

from translator.engines.base import EngineError, EngineStatus, ErrorKind, HtmlSupport
from translator.errors import ApiError
from translator.router import Router
from translator.schemas import TranslateHtmlRequest, TranslateTextRequest


def make_router(*engines: FakeEngine, config=None, retries: int = 0) -> Router:
    config = config or make_config(*(e.id for e in engines))
    return Router(
        list(engines), config, transient_retries=retries, backoff_base_seconds=0
    )


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
            {"id": "off", "kind": "openai", "api_key_env": "NOPE_UNSET_KEY"}
        ],
    )
    router = make_router(FakeEngine("a"), config=config)
    with pytest.raises(ApiError) as excinfo:
        await router.translate_text(TranslateTextRequest(texts=["hi"], engine="off"))
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "engine_disabled"


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


async def test_glossary_unsupported_engine_warns() -> None:
    engine = FakeEngine("a", glossary=False)
    router = make_router(engine)
    resp = await router.translate_html(
        TranslateHtmlRequest(html="<p>萧炎</p>", glossary={"萧炎": "Xiao Yan"})
    )
    assert any("glossary not applied" in w for w in resp.warnings)
