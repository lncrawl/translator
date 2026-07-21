from pathlib import Path

import pytest
from pydantic import ValidationError

from translator.config import AppConfig, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads_and_validates() -> None:
    config = load_config(REPO_ROOT / "config.example.yml")
    assert {e.id for e in config.engines} >= {"zai-glm-flash", "gemini-flash", "deepl"}
    assert config.routing.chapter[0] == "zai-glm-flash"


def test_missing_file_yields_empty_config(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.yml")
    assert config.engines == []


def test_unknown_routing_reference_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown engine"):
        AppConfig.model_validate(
            {
                "engines": [{"id": "a", "kind": "openai"}],
                "routing": {"chapter": ["ghost"]},
            }
        )


def test_duplicate_engine_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        AppConfig.model_validate(
            {"engines": [{"id": "a", "kind": "openai"}, {"id": "a", "kind": "deepl"}]}
        )


def test_engine_disabled_without_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig.model_validate(
        {"engines": [{"id": "a", "kind": "openai", "api_key_env": "SOME_TEST_KEY"}]}
    )
    monkeypatch.delenv("SOME_TEST_KEY", raising=False)
    assert config.engines[0].enabled is False
    monkeypatch.setenv("SOME_TEST_KEY", "secret")
    assert config.engines[0].enabled is True
