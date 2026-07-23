"""Runtime config API: CRUD, atomic apply, and YAML persistence."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from translator.config import AppConfig
from translator.main import create_app

BASE_CONFIG = {
    "providers": [
        {"id": "p1", "kind": "openai", "base_url": "http://one/v1", "api_key": "k1"},
        {"id": "p2", "kind": "openai", "base_url": "http://two/v1", "api_key": "k2"},
    ],
    "engines": [
        {"id": "e1", "provider": "p1", "model": "m1"},
        {"id": "e2", "provider": "p2", "model": "m2"},
    ],
    "routing": {"chapter": ["e1", "e2"], "short_text": ["e1"]},
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    config = AppConfig.model_validate(BASE_CONFIG)
    app = create_app(config, config_path=tmp_path / "config.yml")
    return TestClient(app)


def saved_config(client: TestClient) -> dict:
    path = Path(str(client.app.state.store._path))  # type: ignore[attr-defined]
    return yaml.safe_load(path.read_text())


def test_patch_engine_swaps_model_and_persists(client: TestClient) -> None:
    resp = client.patch("/engines/e1", json={"model": "m1-updated"})
    assert resp.status_code == 200
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["model"] == "m1-updated"
    saved = saved_config(client)
    assert saved["engines"][0]["model"] == "m1-updated"


def test_patch_engine_disable_removes_from_router(client: TestClient) -> None:
    resp = client.patch("/engines/e1", json={"enabled": False})
    assert resp.status_code == 200
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["enabled"] is False
    assert engines["e1"]["status"] == "disabled"


def test_provider_key_set_remotely_enables_engines(client: TestClient) -> None:
    resp = client.patch("/providers/p1", json={"api_key": None})
    assert resp.status_code == 200
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["status"] == "disabled"

    resp = client.patch("/providers/p1", json={"api_key": "fresh"})
    assert resp.status_code == 200
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["status"] == "ok"
    saved = saved_config(client)
    assert saved["providers"][0]["api_key"] == "fresh"


def test_create_engine_on_existing_provider(client: TestClient) -> None:
    resp = client.post(
        "/engines",
        json={"id": "e3", "provider": "p1", "model": "m3"},
    )
    assert resp.status_code == 201
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e3"]["provider"] == "p1"
    # Creating an engine never touches the routing lanes; they are set manually.
    routing = client.get("/config").json()["routing"]
    assert routing["chapter"] == ["e1", "e2"]
    assert routing["short_text"] == ["e1"]


def test_create_engine_unknown_provider_rejected(client: TestClient) -> None:
    resp = client.post("/engines", json={"id": "e3", "provider": "ghost"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_config"


def test_duplicate_engine_rejected(client: TestClient) -> None:
    resp = client.post("/engines", json={"id": "e1", "provider": "p1"})
    assert resp.status_code == 409


def test_engine_id_with_slash_and_colon(client: TestClient) -> None:
    engine_id = "docker.io/qwen3.5:4B-UD-Q4_K_XL"
    resp = client.post("/engines", json={"id": engine_id, "provider": "p1"})
    assert resp.status_code == 201
    quoted = "/engines/docker.io%2Fqwen3.5%3A4B-UD-Q4_K_XL"
    resp = client.patch(quoted, json={"model": "m"})
    assert resp.status_code == 200
    assert client.delete(quoted).status_code == 204
    assert all(e["id"] != engine_id for e in client.get("/config").json()["engines"])


def test_delete_engine_strips_routing(client: TestClient) -> None:
    resp = client.delete("/engines/e1")
    assert resp.status_code == 204
    config = client.get("/config").json()
    assert config["routing"]["chapter"] == ["e2"]
    assert config["routing"]["short_text"] == []
    saved = saved_config(client)
    assert all(e["id"] != "e1" for e in saved["engines"])


def test_delete_provider_in_use_rejected(client: TestClient) -> None:
    resp = client.delete("/providers/p1")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "provider_in_use"


def test_delete_provider_after_engine(client: TestClient) -> None:
    assert client.delete("/engines/e1").status_code == 204
    assert client.delete("/providers/p1").status_code == 204
    config = client.get("/config").json()
    assert all(p["id"] != "p1" for p in config["providers"])


def test_put_routing_validates_references(client: TestClient) -> None:
    resp = client.put("/routing", json={"chapter": ["ghost"]})
    assert resp.status_code == 422
    resp = client.put("/routing", json={"chapter": ["e2"], "short_text": ["e2"]})
    assert resp.status_code == 200
    assert client.get("/config").json()["routing"]["chapter"] == ["e2"]


def test_put_full_config(client: TestClient) -> None:
    new_config = {
        "providers": [{"id": "px", "kind": "openai", "base_url": "http://x/v1"}],
        "engines": [{"id": "ex", "provider": "px", "model": "mx"}],
        "routing": {"chapter": ["ex"], "short_text": ["ex"]},
    }
    resp = client.put("/config", json=new_config)
    assert resp.status_code == 200
    engines = client.get("/engines").json()["engines"]
    assert [e["id"] for e in engines] == ["ex"]
    assert saved_config(client)["engines"][0]["id"] == "ex"


def test_update_failure_policy(client: TestClient) -> None:
    resp = client.put(
        "/config/failure-policy",
        json={"failure_threshold": 5, "cooldown_seconds": 120},
    )
    assert resp.status_code == 200
    policy = client.get("/config").json()["failure_policy"]
    assert policy["failure_threshold"] == 5
    assert policy["cooldown_seconds"] == 120


def test_new_router_serves_after_config_change(client: TestClient) -> None:
    # After a full replace, translation goes through the new engine set.
    # (Engines here are unreachable, so we just assert routing/validation.)
    resp = client.put("/routing", json={"chapter": ["e2"], "short_text": ["e2"]})
    assert resp.status_code == 200
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e2"]["status"] == "ok"
