import pytest
from fastapi.testclient import TestClient

from translator.config import AppConfig
from translator.main import create_app

TEST_CONFIG = AppConfig.model_validate(
    {
        "engines": [
            {
                "id": "llm",
                "kind": "openai",
                "api_key_env": "LLM_TEST_KEY",
                "model": "some-model",
                "max_input_tokens": 100000,
            },
            {"id": "local", "kind": "openai", "base_url": "http://localhost:1"},
        ],
        "routing": {"chapter": ["llm", "local"], "short_text": ["llm"]},
    }
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.delenv("LLM_TEST_KEY", raising=False)
    return TestClient(create_app(TEST_CONFIG))


def test_health_reports_enabled_engines(client: TestClient) -> None:
    body = client.get("/health").json()
    # "llm" lacks its key env, "local" needs none.
    assert body == {"status": "ok", "engines_enabled": ["local"]}


def test_engines_listing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TEST_KEY", "k")
    body = client.get("/engines").json()
    by_id = {e["id"]: e for e in body["engines"]}
    assert by_id["llm"]["status"] == "ok"
    assert by_id["llm"]["capabilities"]["html"] == "prompt"
    assert by_id["llm"]["capabilities"]["max_input_tokens"] == 100000


def test_engines_listing_disabled_without_key(client: TestClient) -> None:
    body = client.get("/engines").json()
    by_id = {e["id"]: e for e in body["engines"]}
    assert by_id["llm"]["status"] == "disabled"
    assert by_id["local"]["status"] == "ok"


def test_detect_endpoint(client: TestClient) -> None:
    resp = client.post("/detect", json={"texts": ["안녕하세요, 소설입니다", "hello"]})
    langs = [r["language"] for r in resp.json()["results"]]
    assert langs[0] == "ko"


def test_translate_endpoints_not_implemented_yet(client: TestClient) -> None:
    resp = client.post("/translate/text", json={"texts": ["你好"], "target_lang": "en"})
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "not_implemented"

    resp = client.post("/translate/html", json={"html": "<p>你好</p>"})
    assert resp.status_code == 501


def test_auth_enforced_when_token_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_TOKEN", "sekret")
    client = TestClient(create_app(TEST_CONFIG))

    assert client.post("/detect", json={"texts": ["hi"]}).status_code == 401
    ok = client.post(
        "/detect",
        json={"texts": ["hi"]},
        headers={"Authorization": "Bearer sekret"},
    )
    assert ok.status_code == 200
    # /health stays open for container liveness probes.
    assert client.get("/health").status_code == 200
