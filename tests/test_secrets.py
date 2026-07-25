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
            "settings": {"base_url": "http://one/v1", "api_key": API_KEY},
        },
        {
            "id": "nokey",
            "kind": "openai",
            "settings": {"base_url": "http://two/v1"},
        },
        {
            "id": "bd",
            "kind": "baidu",
            "settings": {"app_id": "app-123", "secret_key": BAIDU_SECRET},
        },
    ],
    "engines": [{"id": "e1", "provider": "p1", "settings": {"model": "m1"}}],
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
    assert providers["p1"]["settings"]["api_key"] == SECRET_PLACEHOLDER
    # Unset stays unset so clients can tell "configured" from "missing".
    assert "api_key" not in providers["nokey"]["settings"]
    # Secret settings are redacted; non-secret credentials (app_id) are not.
    assert providers["bd"]["settings"]["secret_key"] == SECRET_PLACEHOLDER
    assert providers["bd"]["settings"]["app_id"] == "app-123"
    assert API_KEY not in resp.text
    assert BAIDU_SECRET not in resp.text


def test_put_config_roundtrip_preserves_secrets(client: TestClient) -> None:
    # GET (redacted) -> PUT back unchanged must not wipe or leak secrets.
    config = client.get("/config").json()
    resp = client.put("/config", json=config)
    assert resp.status_code == 200
    assert API_KEY not in resp.text
    assert resp.json()["providers"][0]["settings"]["api_key"] == SECRET_PLACEHOLDER
    assert live_provider(client, "p1").settings["api_key"] == API_KEY
    assert live_provider(client, "bd").settings["secret_key"] == BAIDU_SECRET
    # The real key persists; the placeholder never reaches the config file.
    saved = saved_yaml(client)
    assert API_KEY in saved
    assert SECRET_PLACEHOLDER not in saved
    # Engines keyed by the preserved secret stay enabled.
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["status"] == "ok"


def test_put_config_can_still_replace_a_secret(client: TestClient) -> None:
    config = client.get("/config").json()
    config["providers"][0]["settings"]["api_key"] = "sk-new"
    assert client.put("/config", json=config).status_code == 200
    assert live_provider(client, "p1").settings["api_key"] == "sk-new"


def test_patch_placeholder_keeps_stored_secret(client: TestClient) -> None:
    resp = client.patch(
        "/providers/p1",
        json={"settings": {"api_key": SECRET_PLACEHOLDER, "rpm": 30}},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["api_key"] == SECRET_PLACEHOLDER
    assert API_KEY not in resp.text
    updated = live_provider(client, "p1")
    assert updated.settings["api_key"] == API_KEY
    assert updated.settings["rpm"] == 30


def test_patch_new_secret_is_saved_but_redacted_in_response(
    client: TestClient,
) -> None:
    resp = client.patch("/providers/p1", json={"settings": {"api_key": "sk-fresh"}})
    assert resp.status_code == 200
    assert "sk-fresh" not in resp.text
    assert resp.json()["settings"]["api_key"] == SECRET_PLACEHOLDER
    assert live_provider(client, "p1").settings["api_key"] == "sk-fresh"
    assert "sk-fresh" in saved_yaml(client)


def test_patch_null_clears_secret(client: TestClient) -> None:
    resp = client.patch("/providers/p1", json={"settings": {"api_key": None}})
    assert resp.status_code == 200
    assert resp.json()["settings"]["api_key"] is None
    assert live_provider(client, "p1").settings["api_key"] is None
    engines = {e["id"]: e for e in client.get("/engines").json()["engines"]}
    assert engines["e1"]["status"] == "disabled"


def test_patch_settings_placeholder_keeps_stored_value(client: TestClient) -> None:
    resp = client.patch(
        "/providers/bd",
        json={"settings": {"app_id": "app-456", "secret_key": SECRET_PLACEHOLDER}},
    )
    assert resp.status_code == 200
    assert BAIDU_SECRET not in resp.text
    updated = live_provider(client, "bd")
    assert updated.settings == {"app_id": "app-456", "secret_key": BAIDU_SECRET}


def test_patch_settings_keeps_unmentioned_keys(client: TestClient) -> None:
    # One-level merge, same as the overlay: naming one key must not delete the
    # siblings the patch said nothing about.
    resp = client.patch("/providers/p1", json={"settings": {"api_key": "sk-x"}})
    assert resp.status_code == 200
    assert live_provider(client, "p1").settings["base_url"] == "http://one/v1"


def test_create_provider_never_saves_the_placeholder(client: TestClient) -> None:
    # A placeholder on a new provider has nothing stored behind it: it is
    # dropped, never persisted as a literal credential.
    resp = client.post(
        "/providers",
        json={
            "id": "px",
            "kind": "openai",
            "settings": {
                "base_url": "http://x/v1",
                "api_key": SECRET_PLACEHOLDER,
            },
        },
    )
    assert resp.status_code == 201
    created = live_provider(client, "px")
    assert created.settings == {"base_url": "http://x/v1"}


def test_create_provider_response_is_redacted(client: TestClient) -> None:
    resp = client.post(
        "/providers",
        json={
            "id": "py",
            "kind": "openai",
            "settings": {"base_url": "http://y/v1", "api_key": "sk-created"},
        },
    )
    assert resp.status_code == 201
    assert "sk-created" not in resp.text
    assert resp.json()["settings"]["api_key"] == SECRET_PLACEHOLDER
    assert live_provider(client, "py").settings["api_key"] == "sk-created"


def test_undeclared_settings_key_is_rejected(client: TestClient) -> None:
    # extra="forbid" on the kind's model: a key nobody declared is a typo, and
    # the served schema is only authoritative if unknown keys cannot be stored.
    resp = client.patch("/providers/p1", json={"settings": {"org_token": "x"}})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_config"


def test_undeclared_settings_keys_redact_by_default() -> None:
    # Validation normally rejects them, but redaction must stay safe on any
    # dict that reached us without it — deny by default, never opt-in.
    from translator.config import ProviderConfig
    from translator.server.secrets import redact_provider

    provider = ProviderConfig.model_validate(
        {"id": "p", "kind": "openai", "settings": {"org_token": "org-secret"}}
    )
    assert redact_provider(provider).settings["org_token"] == SECRET_PLACEHOLDER


def test_openapi_and_schema_endpoints_leak_nothing(client: TestClient) -> None:
    for path in ("/openapi.json", "/schema", "/engines", "/health", "/config"):
        body = client.get(path).text
        assert API_KEY not in body
        assert BAIDU_SECRET not in body


def test_saved_overlay_still_carries_real_secrets(client: TestClient) -> None:
    # Persistence (the YAML file) is storage, not an interface: after a
    # mutation the file must hold real credentials so a restart keeps working.
    client.patch("/engines/e1", json={"settings": {"model": "m2"}})
    saved = yaml.safe_load(saved_yaml(client))
    p1 = next(p for p in saved["providers"] if p["id"] == "p1")
    assert p1["settings"]["api_key"] == API_KEY
