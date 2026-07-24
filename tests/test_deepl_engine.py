from __future__ import annotations

import json

import httpx
import pytest
from helpers import make_resolved

from translator.engines.base import EngineError, ErrorKind
from translator.engines.deepl import DeepLEngine


def make_engine(handler: httpx.MockTransport) -> DeepLEngine:
    config = make_resolved("deepl", kind="deepl", base_url=None, api_key="secret:fx")
    engine = DeepLEngine(config)
    engine._client = httpx.AsyncClient(
        base_url="https://api-free.deepl.com", transport=handler
    )
    return engine


async def test_free_key_selects_free_base_url() -> None:
    config = make_resolved("deepl", kind="deepl", base_url=None, api_key="secret:fx")
    engine = DeepLEngine(config)
    assert str(engine._client.base_url).startswith("https://api-free.deepl.com")
    await engine.close()


async def test_translate_html_uses_tag_handling() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "translations": [
                    {"detected_source_language": "ZH", "text": "<p>Hello</p>"}
                ]
            },
        )

    engine = make_engine(httpx.MockTransport(handler))
    result = await engine.translate_html(
        "<p>你好</p>", source_lang="zh", target_lang="en", glossary={}
    )
    assert result.html == "<p>Hello</p>"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["tag_handling"] == "html"
    assert body["target_lang"] == "EN-US"
    assert body["source_lang"] == "ZH"


async def test_456_is_quota_until_next_month() -> None:
    engine = make_engine(
        httpx.MockTransport(lambda _: httpx.Response(456, text="quota exceeded"))
    )
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="en", target_lang="zh", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.QUOTA
    assert excinfo.value.retry_after_seconds is not None
    assert excinfo.value.retry_after_seconds >= 3600
