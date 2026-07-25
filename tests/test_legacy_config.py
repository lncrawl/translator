"""Backward compatibility with pre-``settings`` config files.

Deleted together with ``translator/config/legacy.py`` when the old formats are
dropped. Nothing outside this file should depend on the compatibility path —
keep new tests on the nested shape.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from translator.config import AppConfig, load_config
from translator.engines import resolve
from translator.server.app import create_app


def test_flat_engine_becomes_engine_plus_provider() -> None:
    config = AppConfig.model_validate(
        {
            "engines": [
                {
                    "id": "old-style",
                    "kind": "openai",
                    "base_url": "http://x/v1",
                    "api_key": "sk-test",
                    "rpm": 10,
                    "model": "m1",
                    "max_input_tokens": 8000,
                }
            ],
            "routing": {"chapter": ["old-style"]},
        }
    )
    provider = config.provider("old-style")
    assert provider is not None
    assert provider.settings["base_url"] == "http://x/v1"
    assert provider.settings["api_key"] == "sk-test"
    assert provider.settings["rpm"] == 10

    resolved = resolve(config, "old-style")
    assert resolved is not None
    assert resolved.engine_settings.max_input_tokens == 8000
    # `model` is an engine setting and must survive the provider split.
    assert resolved.engine_settings.model == "m1"  # type: ignore[attr-defined]


def test_flat_extra_body_survives_the_provider_split() -> None:
    config = AppConfig.model_validate(
        {
            "engines": [
                {
                    "id": "old",
                    "kind": "openai",
                    "base_url": "http://x/v1",
                    "requires_key": False,
                    "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                }
            ]
        }
    )
    resolved = resolve(config, "old")
    assert resolved is not None
    assert resolved.engine_settings.extra_body == {  # type: ignore[attr-defined]
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_options_bag_is_spliced_into_settings() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [
                {
                    "id": "baidu",
                    "kind": "baidu",
                    "options": {"app_id": "a", "secret_key": "s"},
                }
            ],
            "engines": [{"id": "b", "provider": "baidu"}],
        }
    )
    provider = config.provider("baidu")
    assert provider is not None
    assert provider.settings == {"app_id": "a", "secret_key": "s"}


def test_retired_keys_are_dropped() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [
                {
                    "id": "d",
                    "kind": "deepl",
                    "api_key": "k",
                    "monthly_chars": 500_000,
                }
            ],
            "engines": [{"id": "e", "provider": "d"}],
        }
    )
    provider = config.provider("d")
    assert provider is not None
    assert provider.settings == {"api_key": "k"}


def test_flat_overlay_composes_with_a_nested_default(tmp_path: Path) -> None:
    # The hoist runs on the entry models, after the raw-dict merge, so an old
    # file still layers correctly onto a default written in the new shape.
    path = tmp_path / "config.yml"
    path.write_text("providers:\n  - id: gemini\n    api_key: k\n", encoding="utf-8")
    config = load_config(path)
    gemini = config.provider("gemini")
    assert gemini is not None
    assert gemini.settings["api_key"] == "k"
    assert (
        gemini.settings["base_url"]
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )


def test_flat_config_skips_default_merge(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        "engines:\n  - id: solo\n    kind: openai\n    base_url: http://x\n"
        "    requires_key: false\nrouting:\n  chapter: [solo]\n",
        encoding="utf-8",
    )
    config = load_config(path)
    # Legacy flat files load standalone — defaults are NOT merged in.
    assert {e.id for e in config.engines} == {"solo"}


def test_flat_patch_body_still_sets_a_credential(tmp_path: Path) -> None:
    config = AppConfig.model_validate(
        {
            "providers": [
                {"id": "p", "kind": "openai", "settings": {"base_url": "http://x/v1"}}
            ],
            "engines": [{"id": "a", "provider": "p"}],
        }
    )
    app = create_app(config=config, config_path=tmp_path / "config.yml")
    with TestClient(app) as client:
        response = client.patch("/providers/p", json={"api_key": "sk-flat"})
        assert response.status_code == 200
        # Written into settings, and the sibling base_url is untouched.
        assert response.json()["settings"]["base_url"] == "http://x/v1"
        saved = client.get("/config").json()
        assert saved["providers"][0]["settings"]["api_key"] == "__secret__"
