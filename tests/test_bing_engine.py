from __future__ import annotations

import json

import httpx
import pytest
from helpers import make_resolved

from translator.engines.base import ErrorKind, HtmlSupport
from translator.engines.bing import BingEngine


def make_engine(handler: httpx.MockTransport) -> BingEngine:
    config = make_resolved("bing", kind="bing", base_url=None, requires_key=False)
    engine = BingEngine(config)
    engine._client = httpx.AsyncClient(transport=handler)
    return engine


def _handler(translate: httpx.Response) -> httpx.MockTransport:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "edge.microsoft.com":
            return httpx.Response(200, text="TOKEN123")
        return translate

    return httpx.MockTransport(route)


def test_capabilities_are_html_native() -> None:
    engine = make_engine(_handler(httpx.Response(200, json=[])))
    caps = engine.capabilities
    assert caps.html is HtmlSupport.NATIVE
    assert caps.glossary is False


async def test_translate_segments_aligns_and_maps_language() -> None:
    seen: dict[str, object] = {}

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "edge.microsoft.com":
            return httpx.Response(200, text="TOKEN123")
        seen["params"] = dict(request.url.params)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=[
                {"translations": [{"text": "Xiao Yan"}]},
                {"translations": [{"text": "Dou Qi"}]},
            ],
        )

    engine = make_engine(httpx.MockTransport(route))
    out = await engine.translate_segments(
        ["萧炎", "斗气"], source_lang="zh", target_lang="en", glossary={}
    )
    assert out == ["Xiao Yan", "Dou Qi"]
    assert seen["auth"] == "Bearer TOKEN123"
    params = seen["params"]
    assert isinstance(params, dict)
    assert params["to"] == "en"
    assert params["from"] == "zh-Hans"  # zh canonicalizes to a script for MS


async def test_translate_html_sets_texttype() -> None:
    seen: dict[str, object] = {}

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "edge.microsoft.com":
            return httpx.Response(200, text="TOKEN123")
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"translations": [{"text": "<p>Hi</p>"}]}])

    engine = make_engine(httpx.MockTransport(route))
    result = await engine.translate_html(
        "<p>你好</p>", source_lang="zh", target_lang="en", glossary={}
    )
    assert result.html == "<p>Hi</p>"
    params = seen["params"]
    assert isinstance(params, dict)
    assert params["textType"] == "html"


async def test_429_is_quota() -> None:
    engine = make_engine(_handler(httpx.Response(429, text="rate limited")))
    with pytest.raises(Exception) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="en", target_lang="zh", glossary={}
        )
    assert getattr(excinfo.value, "kind", None) is ErrorKind.QUOTA


async def test_401_is_transient_and_resets_token() -> None:
    engine = make_engine(_handler(httpx.Response(401, text="expired")))
    with pytest.raises(Exception) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="en", target_lang="zh", glossary={}
        )
    assert getattr(excinfo.value, "kind", None) is ErrorKind.TRANSIENT
    assert engine._token_expiry == float("-inf")
