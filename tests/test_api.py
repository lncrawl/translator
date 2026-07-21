import pytest
from fastapi.testclient import TestClient
from helpers import FakeEngine, make_config

from translator.config import AppConfig
from translator.engines.base import EngineError, ErrorKind
from translator.main import create_app
from translator.router import Router

BOOT_CONFIG = AppConfig.model_validate(
    {
        "engines": [
            {
                "id": "llm",
                "kind": "openai",
                "base_url": "http://fake",
                "api_key_env": "LLM_TEST_KEY",
                "model": "some-model",
                "max_input_tokens": 100000,
            },
            {"id": "local", "kind": "openai", "base_url": "http://localhost:1"},
        ],
        "routing": {"chapter": ["llm", "local"], "short_text": ["llm", "local"]},
    }
)


def fake_client(*engines: FakeEngine, config: AppConfig | None = None) -> TestClient:
    config = config or make_config(*(e.id for e in engines))
    router = Router(list(engines), config, transient_retries=0, backoff_base_seconds=0)
    return TestClient(create_app(config, router))


@pytest.fixture
def boot_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.delenv("LLM_TEST_KEY", raising=False)
    return TestClient(create_app(BOOT_CONFIG))


def test_health_reports_enabled_engines(boot_client: TestClient) -> None:
    body = boot_client.get("/health").json()
    # "llm" lacks its key env, "local" needs none.
    assert body == {"status": "ok", "engines_enabled": ["local"]}


def test_engines_listing_reflects_boot_time_keys(
    boot_client: TestClient,
) -> None:
    body = boot_client.get("/engines").json()
    by_id = {e["id"]: e for e in body["engines"]}
    assert by_id["llm"]["status"] == "disabled"
    assert by_id["local"]["status"] == "ok"
    assert by_id["llm"]["capabilities"]["html"] == "prompt"
    assert by_id["llm"]["capabilities"]["max_input_tokens"] == 100000


def test_engines_listing_with_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.setenv("LLM_TEST_KEY", "k")
    client = TestClient(create_app(BOOT_CONFIG))
    by_id = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert by_id["llm"]["status"] == "ok"


def test_detect_endpoint(boot_client: TestClient) -> None:
    resp = boot_client.post(
        "/detect", json={"texts": ["안녕하세요, 소설입니다", "hello"]}
    )
    langs = [r["language"] for r in resp.json()["results"]]
    assert langs[0] == "ko"


def test_translate_text_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    client = fake_client(FakeEngine("fake"))
    resp = client.post("/translate/text", json={"texts": ["你好"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["translations"] == ["fake:你好"]
    assert body["engine"] == "fake"
    assert body["detected_source_lang"] == "zh"


def test_translate_html_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
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
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
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
    assert by_id["fake"]["quota_resets_at"] is not None


def test_auth_enforced_when_token_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_TOKEN", "sekret")
    monkeypatch.delenv("LLM_TEST_KEY", raising=False)
    client = TestClient(create_app(BOOT_CONFIG))

    assert client.post("/detect", json={"texts": ["hi"]}).status_code == 401
    ok = client.post(
        "/detect",
        json={"texts": ["hi"]},
        headers={"Authorization": "Bearer sekret"},
    )
    assert ok.status_code == 200
    # /health stays open for container liveness probes.
    assert client.get("/health").status_code == 200
