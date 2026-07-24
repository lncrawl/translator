from __future__ import annotations

import json

import httpx
import pytest
from helpers import make_resolved

from translator.engines.base import EngineError, ErrorKind
from translator.engines.openai_compat import OpenAICompatEngine


def make_engine(handler: httpx.MockTransport) -> OpenAICompatEngine:
    config = make_resolved(model="test-model")
    engine = OpenAICompatEngine(config)
    engine._client = httpx.AsyncClient(base_url="http://fake/v1", transport=handler)
    return engine


def completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_translate_segments() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return completion('["hello", "world"]')

    engine = make_engine(httpx.MockTransport(handler))
    result = await engine.translate_segments(
        ["你好", "世界"],
        source_lang="zh",
        target_lang="en",
        glossary={},
    )
    assert result == ["hello", "world"]
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "test-model"
    assert "你好" in body["messages"][1]["content"]


async def test_extra_body_merged_into_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return completion('["hi"]')

    config = make_resolved(
        model="test-model",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    engine = OpenAICompatEngine(config)
    engine._client = httpx.AsyncClient(
        base_url="http://fake/v1", transport=httpx.MockTransport(handler)
    )
    await engine.translate_segments(
        ["你好"], source_lang="zh", target_lang="en", glossary={}
    )
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


async def test_translate_segments_bad_reply_is_transient() -> None:
    engine = make_engine(
        httpx.MockTransport(lambda _: completion("I refuse to answer."))
    )
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["你好"], source_lang="zh", target_lang="en", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.TRANSIENT


async def test_translate_html_with_markers_and_terms() -> None:
    reply = (
        "<TRANSLATION><p>Xiao Yan met Yao Lao.</p></TRANSLATION>"
        '<NEW_TERMS>{"药老": "Yao Lao", "萧炎": "Xiao Yan"}</NEW_TERMS>'
    )
    engine = make_engine(httpx.MockTransport(lambda _: completion(reply)))
    result = await engine.translate_html(
        "<p>萧炎见到了药老。</p>",
        source_lang="zh",
        target_lang="en",
        glossary={"萧炎": "Xiao Yan"},
    )
    assert result.html == "<p>Xiao Yan met Yao Lao.</p>"
    # Terms already in the glossary are dropped from new_terms.
    assert result.new_terms == {"药老": "Yao Lao"}
    assert result.warnings == []


async def test_translate_html_drops_invalid_new_terms() -> None:
    reply = (
        "<TRANSLATION><p>Xiao Yan entered the Heavenly Punishment Forest.</p>"
        "</TRANSLATION>"
        '<NEW_TERMS>{"天罚森林": "Heavenly Punishment Forest",'
        ' "Chaos Body": "Chaos Body",'
        ' "Imperial Bone": "Imperial Bone"}</NEW_TERMS>'
    )
    engine = make_engine(httpx.MockTransport(lambda _: completion(reply)))
    result = await engine.translate_html(
        "<p>萧炎走进了天罚森林。</p>",
        source_lang="zh",
        target_lang="en",
        glossary={"萧炎": "Xiao Yan"},
    )
    # Only keys that literally occur in the source survive; identity pairs
    # and translated-English keys are dropped.
    assert result.new_terms == {"天罚森林": "Heavenly Punishment Forest"}


async def test_translate_html_retries_on_cjk_leak_then_warns() -> None:
    reply = (
        "<TRANSLATION><p>The blood wheel began to re凝聚起来 above his"
        " head.</p></TRANSLATION>"
    )
    calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["temperature"])
        return completion(reply)

    engine = make_engine(httpx.MockTransport(handler))
    result = await engine.translate_html(
        "<p>血轮开始重新凝聚起来。</p>",
        source_lang="zh",
        target_lang="en",
        glossary={},
    )
    # One regeneration at higher temperature, then an honest warning.
    assert calls == [0.3, 0.6]
    assert any("untranslated CJK" in w for w in result.warnings)


async def test_translate_html_retry_recovers_from_cjk_leak() -> None:
    replies = iter(
        [
            "<TRANSLATION><p>It began to re凝聚 above his head.</p></TRANSLATION>",
            "<TRANSLATION><p>It began to recondense above his head.</p></TRANSLATION>",
        ]
    )
    engine = make_engine(httpx.MockTransport(lambda _: completion(next(replies))))
    result = await engine.translate_html(
        "<p>血轮开始重新凝聚。</p>",
        source_lang="zh",
        target_lang="en",
        glossary={},
    )
    assert result.html == "<p>It began to recondense above his head.</p>"
    assert result.warnings == []


async def test_translate_html_clean_output_needs_no_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return completion("<TRANSLATION><p>Hello there.</p></TRANSLATION>")

    engine = make_engine(httpx.MockTransport(handler))
    result = await engine.translate_html(
        "<p>你好。</p>", source_lang="zh", target_lang="en", glossary={}
    )
    assert result.html == "<p>Hello there.</p>"
    assert len(calls) == 1


async def test_translate_html_plain_text_reply_is_repaired() -> None:
    engine = make_engine(
        httpx.MockTransport(lambda _: completion("Hello.\n\nGoodbye."))
    )
    result = await engine.translate_html(
        "<p>你好。</p><p>再见。</p>",
        source_lang="zh",
        target_lang="en",
        glossary={},
    )
    assert result.html == "<p>Hello.</p><p>Goodbye.</p>"
    assert any("re-wrapped" in w for w in result.warnings)


async def test_429_with_long_retry_after_is_quota() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "86400"}, text="quota")

    engine = make_engine(httpx.MockTransport(handler))
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="en", target_lang="zh", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.QUOTA
    assert excinfo.value.retry_after_seconds == 86400


async def test_429_with_short_retry_after_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "2"}, text="slow down")

    engine = make_engine(httpx.MockTransport(handler))
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="en", target_lang="zh", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.TRANSIENT


async def test_server_error_is_transient_and_401_is_fatal() -> None:
    for status, kind in ((500, ErrorKind.TRANSIENT), (401, ErrorKind.FATAL)):
        engine = make_engine(
            httpx.MockTransport(lambda _, s=status: httpx.Response(s, text="err"))
        )
        with pytest.raises(EngineError) as excinfo:
            await engine.translate_segments(
                ["hi"], source_lang="en", target_lang="zh", glossary={}
            )
        assert excinfo.value.kind is kind
