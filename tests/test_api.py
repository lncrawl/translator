import pytest
from fastapi.testclient import TestClient
from helpers import FakeEngine, make_config

from translator.config import AppConfig
from translator.engines.base import EngineError, ErrorKind
from translator.main import create_app
from translator.router import Router

# "llm" requires a key that is not set; "local" declares it needs none.
BOOT_CONFIG_DATA = {
    "engines": [
        {
            "id": "llm",
            "kind": "openai",
            "base_url": "http://fake",
            "model": "some-model",
            "max_input_tokens": 100000,
        },
        {
            "id": "local",
            "kind": "openai",
            "base_url": "http://localhost:1",
            "requires_key": False,
        },
    ],
    "routing": {"chapter": ["llm", "local"], "short_text": ["llm", "local"]},
}
BOOT_CONFIG = AppConfig.model_validate(BOOT_CONFIG_DATA)


def fake_client(*engines: FakeEngine, config: AppConfig | None = None) -> TestClient:
    config = config or make_config(*(e.id for e in engines))
    router = Router(list(engines), config, transient_retries=0, backoff_base_seconds=0)
    return TestClient(create_app(config, router))


@pytest.fixture
def boot_client() -> TestClient:
    return TestClient(create_app(BOOT_CONFIG))


def test_root_serves_demo_page(boot_client: TestClient) -> None:
    resp = boot_client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<title>translator" in resp.text


def test_health_reports_enabled_engines(boot_client: TestClient) -> None:
    body = boot_client.get("/health").json()
    assert body["status"] == "ok"
    assert body["engines_enabled"] == ["local"]
    assert body["version"]


def test_engines_listing_reflects_boot_time_keys(
    boot_client: TestClient,
) -> None:
    body = boot_client.get("/engines").json()
    by_id = {e["id"]: e for e in body["engines"]}
    assert by_id["llm"]["status"] == "disabled"
    assert by_id["llm"]["enabled"] is False
    assert by_id["local"]["status"] == "ok"
    assert by_id["local"]["enabled"] is True
    assert by_id["llm"]["capabilities"]["html"] == "prompt"
    assert by_id["llm"]["capabilities"]["max_input_tokens"] == 100000


def test_engines_listing_with_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    keyed = AppConfig.model_validate(BOOT_CONFIG_DATA)
    provider = keyed.provider("llm")
    assert provider is not None
    provider.api_key = "k"
    client = TestClient(create_app(keyed))
    by_id = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert by_id["llm"]["status"] == "ok"


def test_detect_endpoint(boot_client: TestClient) -> None:
    resp = boot_client.post(
        "/detect", json={"texts": ["안녕하세요, 소설입니다", "hello"]}
    )
    langs = [r["language"] for r in resp.json()["results"]]
    assert langs[0] == "ko"


def test_translate_text_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fake_client(FakeEngine("fake"))
    resp = client.post("/translate/text", json={"texts": ["你好"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["translations"] == ["fake:你好"]
    assert body["engine"] == "fake"
    assert body["detected_source_lang"] == "zh"


def test_translate_html_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fake_client(FakeEngine("fake", new_terms={"药老": "Yao Lao"}))
    resp = client.post(
        "/translate/html",
        json={"html": "<p>萧炎见到了药老。</p>", "glossary": {"萧炎": "Xiao Yan"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["html"] == "[fake]<p>萧炎见到了药老。</p>"
    assert body["new_terms"] == {"药老": "Yao Lao"}


def test_quota_exhaustion_surfaces_as_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(
        "fake", errors=[EngineError("q", ErrorKind.QUOTA, retry_after_seconds=60)]
    )
    client = fake_client(engine)
    resp = client.post("/translate/text", json={"texts": ["hi"]})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "all_engines_exhausted"
    assert "Retry-After" in resp.headers

    by_id = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert by_id["fake"]["status"] == "quota_exhausted"
    assert by_id["fake"]["retry_at"] is not None


def test_invalid_lang_tags_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fake_client(FakeEngine("fake"))
    for bad in ("english", "e", "zh_CN", "zh-CN-Hant", "zh-Hantt"):
        resp = client.post(
            "/translate/text", json={"texts": ["hi"], "target_lang": bad}
        )
        assert resp.status_code == 422, bad


def test_lang_tags_accept_variants_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = fake_client(FakeEngine("fake"))
    for tag in ("EN", "zh-tw", "zh-Hant", "pt-br"):
        resp = client.post(
            "/translate/text",
            json={"texts": ["你好"], "source_lang": "ZH", "target_lang": tag},
        )
        assert resp.status_code == 200, tag


def test_oversized_html_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fake_client(FakeEngine("fake"))
    resp = client.post(
        "/translate/html", json={"html": "<p>" + "x" * 1_000_000 + "</p>"}
    )
    assert resp.status_code == 422


def test_unexpected_error_returns_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine("fake", errors=[RuntimeError("boom"), RuntimeError("boom")])
    config = make_config("fake")
    router = Router([engine], config, transient_retries=0, backoff_base_seconds=0)
    client = TestClient(create_app(config, router), raise_server_exceptions=False)
    resp = client.post("/translate/text", json={"texts": ["hi"]})
    assert resp.status_code == 500
    assert resp.json() == {
        "error": {"code": "internal_error", "message": "internal server error"}
    }


def test_oversized_body_rejected_with_413(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fake_client(FakeEngine("fake"))
    resp = client.post(
        "/translate/html",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(20 * 1024 * 1024),
        },
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"
