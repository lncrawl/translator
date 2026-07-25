"""Provider secrets are write-only: set through the API, never read back."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from translator.config import AppConfig
from translator.server import create_app
from translator.server.secrets import SECRET_PLACEHOLDER

API_KEY = "sk-real-token-1"
BAIDU_SECRET = "baidu-secret-key"

BASE_CONFIG = {
    "providers": [
        {
            "id": "p1",
            "kind": "openai",
            "base_url": "http://one/v1",
            "api_key": API_KEY,
        },
        {"id": "nokey", "kind": "openai", "base_url": "http://two/v1"},
        {
            "id": "bd",
            "kind": "baidu",
            "options": {"app_id": "app-123", "secret_key": BAIDU_SECRET},
        },
    ],
    "engines": [{"id": "e1", "provider": "p1", "model": "m1"}],
    "routing": {"chapter": ["e1"], "short_text": ["e1"]},
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    config = AppConfig.model_validate(BASE_CONFIG)
    app = create_app(config, config_path=tmp_path / "config.yml")
    return TestClient(app)


def saved_yaml(client: TestClient) -> str:
    path = Path(str(client.app.state.store._path))  # type: ignore[attr-defined]
    return path.read_text()


def live_provider(client: TestClient, provider_id: str):
    provider = client.app.state.store.config.provider(provider_id)  # type: ignore[attr-defined]
    assert provider is not None
    return provider


def test_get_config_redacts_secrets(client: TestClient) -> None:
    resp = client.get("/config")
    providers = {p["id"]: p for p in resp.json()["providers"]}
    assert providers["p1"]["api_key"] == SECRET_PLACEHOLDER
    # Unset stays unset so clients can tell "configured" from "missing".
    assert providers["nokey"]["api_key"] is None
    # Secret options are redacted; non-secret credentials (app_id) are not.
    assert providers["bd"]["options"]["secret_key"] == SECRET_PLACEHOLDER
    assert providers["bd"]["options"]["app_id"] == "app-123"
    assert API_KEY not in resp.text
    assert BAIDU_SECRET not in resp.text


def test_put_config_roundtrip_preserves_secrets(client: TestClient) -> None:
    # GET (redacted) -> PUT back unchanged must not wipe or leak secrets.
    config = client.get("/config").json()
    resp = client.put("/config", json=config)
    assert resp.status_code == 200
    assert API_KEY not in resp.text
    assert resp.json()["providers"][0]["api_key"] == SECRET_PLACEHOLDER
    assert live_provider(client, "p1").api_key == API_KEY
    assert live_provider(client, "bd").options["secret_key"] == BAIDU_SECRET
    # The real key persists; the placeholder never reaches the config file.
    saved = saved_yaml(client)
    assert API_KEY in saved
    assert SECRET_PLACEHOLDER not in saved
    # Engines keyed by the preserved secret stay enabled.
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["status"] == "ok"


def test_put_config_can_still_replace_a_secret(client: TestClient) -> None:
    config = client.get("/config").json()
    config["providers"][0]["api_key"] = "sk-new"
    assert client.put("/config", json=config).status_code == 200
    assert live_provider(client, "p1").api_key == "sk-new"


def test_patch_placeholder_keeps_stored_secret(client: TestClient) -> None:
    resp = client.patch(
        "/providers/p1", json={"api_key": SECRET_PLACEHOLDER, "rpm": 30}
    )
    assert resp.status_code == 200
    assert resp.json()["api_key"] == SECRET_PLACEHOLDER
    assert API_KEY not in resp.text
    updated = live_provider(client, "p1")
    assert updated.api_key == API_KEY
    assert updated.rpm == 30


def test_patch_new_secret_is_saved_but_redacted_in_response(
    client: TestClient,
) -> None:
    resp = client.patch("/providers/p1", json={"api_key": "sk-fresh"})
    assert resp.status_code == 200
    assert "sk-fresh" not in resp.text
    assert resp.json()["api_key"] == SECRET_PLACEHOLDER
    assert live_provider(client, "p1").api_key == "sk-fresh"
    assert "sk-fresh" in saved_yaml(client)


def test_patch_null_clears_secret(client: TestClient) -> None:
    resp = client.patch("/providers/p1", json={"api_key": None})
    assert resp.status_code == 200
    assert resp.json()["api_key"] is None
    assert live_provider(client, "p1").api_key is None
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["status"] == "disabled"


def test_patch_options_placeholder_keeps_stored_value(client: TestClient) -> None:
    resp = client.patch(
        "/providers/bd",
        json={"options": {"app_id": "app-456", "secret_key": SECRET_PLACEHOLDER}},
    )
    assert resp.status_code == 200
    assert BAIDU_SECRET not in resp.text
    updated = live_provider(client, "bd")
    assert updated.options == {"app_id": "app-456", "secret_key": BAIDU_SECRET}


def test_create_provider_never_saves_the_placeholder(client: TestClient) -> None:
    # A placeholder on a new provider has nothing stored behind it: it is
    # dropped, never persisted as a literal credential.
    resp = client.post(
        "/providers",
        json={
            "id": "px",
            "kind": "openai",
            "base_url": "http://x/v1",
            "api_key": SECRET_PLACEHOLDER,
            "options": {"extra": SECRET_PLACEHOLDER},
        },
    )
    assert resp.status_code == 201
    created = live_provider(client, "px")
    assert created.api_key is None
    assert created.options == {}


def test_create_provider_response_is_redacted(client: TestClient) -> None:
    resp = client.post(
        "/providers",
        json={
            "id": "py",
            "kind": "openai",
            "base_url": "http://y/v1",
            "api_key": "sk-created",
        },
    )
    assert resp.status_code == 201
    assert "sk-created" not in resp.text
    assert resp.json()["api_key"] == SECRET_PLACEHOLDER
    assert live_provider(client, "py").api_key == "sk-created"


def test_unknown_option_keys_are_treated_as_secret(client: TestClient) -> None:
    resp = client.patch("/providers/p1", json={"options": {"org_token": "org-secret"}})
    assert resp.status_code == 200
    assert "org-secret" not in resp.text
    assert resp.json()["options"]["org_token"] == SECRET_PLACEHOLDER


def test_openapi_and_schema_endpoints_leak_nothing(client: TestClient) -> None:
    for path in ("/openapi.json", "/credential-schema", "/engines", "/health"):
        body = client.get(path).text
        assert API_KEY not in body
        assert BAIDU_SECRET not in body


def test_saved_overlay_still_carries_real_secrets(client: TestClient) -> None:
    # Persistence (the YAML file) is storage, not an interface: after a
    # mutation the file must hold real credentials so a restart keeps working.
    client.patch("/engines/e1", json={"model": "m2"})
    saved = yaml.safe_load(saved_yaml(client))
    p1 = next(p for p in saved["providers"] if p["id"] == "p1")
    assert p1["api_key"] == API_KEY
