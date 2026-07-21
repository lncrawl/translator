import json

import httpx
import pytest

from translator.config import EngineConfig
from translator.engines.base import EngineError, ErrorKind
from translator.engines.deepl import DeepLEngine


def make_engine(
    handler: httpx.MockTransport, monkeypatch: pytest.MonkeyPatch
) -> DeepLEngine:
    monkeypatch.setenv("DEEPL_TEST_KEY", "secret:fx")
    config = EngineConfig(id="deepl", kind="deepl", api_key_env="DEEPL_TEST_KEY")
    engine = DeepLEngine(config)
    engine._client = httpx.AsyncClient(
        base_url="https://api-free.deepl.com", transport=handler
    )
    return engine


async def test_free_key_selects_free_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPL_TEST_KEY", "secret:fx")
    config = EngineConfig(id="deepl", kind="deepl", api_key_env="DEEPL_TEST_KEY")
    engine = DeepLEngine(config)
    assert str(engine._client.base_url).startswith("https://api-free.deepl.com")
    await engine.close()


async def test_translate_html_uses_tag_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    engine = make_engine(httpx.MockTransport(handler), monkeypatch)
    result = await engine.translate_html(
        "<p>你好</p>", source_lang="zh", target_lang="en", glossary={}
    )
    assert result.html == "<p>Hello</p>"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["tag_handling"] == "html"
    assert body["target_lang"] == "EN-US"
    assert body["source_lang"] == "ZH"


async def test_456_is_quota_until_next_month(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_engine(
        httpx.MockTransport(lambda _: httpx.Response(456, text="quota exceeded")),
        monkeypatch,
    )
    with pytest.raises(EngineError) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="en", target_lang="zh", glossary={}
        )
    assert excinfo.value.kind is ErrorKind.QUOTA
    assert excinfo.value.retry_after_seconds is not None
    assert excinfo.value.retry_after_seconds >= 3600
