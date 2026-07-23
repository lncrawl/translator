from urllib.parse import parse_qs

import httpx
import pytest
from helpers import make_resolved

from translator.engines.baidu import BaiduEngine
from translator.engines.base import ErrorKind, HtmlSupport


def make_engine(
    handler: httpx.MockTransport, *, api_key: str = "app123:secret"
) -> BaiduEngine:
    config = make_resolved("baidu", kind="baidu", base_url=None, api_key=api_key)
    engine = BaiduEngine(config)
    engine._client = httpx.AsyncClient(transport=handler)
    return engine


def test_capabilities_are_text_only() -> None:
    engine = make_engine(httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    caps = engine.capabilities
    assert caps.html is HtmlSupport.NONE
    assert caps.glossary is False


def test_malformed_key_rejected() -> None:
    config = make_resolved("baidu", kind="baidu", base_url=None, api_key="appid-only")
    with pytest.raises(ValueError):
        BaiduEngine(config)


async def test_translate_segments_batches_and_signs() -> None:
    seen: dict[str, object] = {}

    def route(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        seen["form"] = form
        lines = form["q"].split("\n")
        return httpx.Response(
            200,
            json={
                "from": "zh",
                "to": "en",
                "trans_result": [{"src": ln, "dst": f"T:{ln}"} for ln in lines],
            },
        )

    engine = make_engine(httpx.MockTransport(route))
    out = await engine.translate_segments(
        ["萧炎", "", "斗气"], source_lang="zh", target_lang="en", glossary={}
    )
    # Empty segment passes through untouched; others translated and aligned.
    assert out == ["T:萧炎", "", "T:斗气"]
    form = seen["form"]
    assert isinstance(form, dict)
    assert form["from"] == "auto"
    assert form["to"] == "en"
    assert form["appid"] == "app123"
    assert len(form["sign"]) == 32  # md5 hexdigest


async def test_unsupported_target_is_fatal() -> None:
    engine = make_engine(httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    with pytest.raises(Exception) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="en", target_lang="xx", glossary={}
        )
    assert getattr(excinfo.value, "kind", None) is ErrorKind.FATAL


async def test_quota_and_transient_error_codes() -> None:
    engine = make_engine(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"error_code": "54004", "error_msg": "balance"}
            )
        )
    )
    with pytest.raises(Exception) as excinfo:
        await engine.translate_segments(
            ["hi"], source_lang="zh", target_lang="en", glossary={}
        )
    assert getattr(excinfo.value, "kind", None) is ErrorKind.QUOTA

    engine2 = make_engine(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"error_code": "54003", "error_msg": "rate"}
            )
        )
    )
    with pytest.raises(Exception) as excinfo2:
        await engine2.translate_segments(
            ["hi"], source_lang="zh", target_lang="en", glossary={}
        )
    assert getattr(excinfo2.value, "kind", None) is ErrorKind.TRANSIENT
