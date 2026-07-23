from pathlib import Path

import pytest
from pydantic import ValidationError

from translator.config import AppConfig, load_config, save_config
from translator.engines import is_available

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads_and_validates() -> None:
    config = load_config(REPO_ROOT / "config.example.yml")
    assert {e.id for e in config.engines} >= {"zai-glm-flash", "gemini-flash"}
    # The template ships without keys, so only the keyless NLLB lane routes.
    assert config.routing.chapter == ["nllb"]
    assert [r.id for r in config.resolved_engines() if is_available(r)] == ["nllb"]
    resolved = config.resolved("zai-glm-flash")
    assert resolved is not None
    assert resolved.base_url == "https://api.z.ai/api/paas/v4"


def test_legacy_flat_config_is_migrated() -> None:
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
    assert provider.base_url == "http://x/v1"
    assert provider.api_key == "sk-test"
    assert provider.rpm == 10
    resolved = config.resolved("old-style")
    assert resolved is not None
    assert resolved.model == "m1"
    assert resolved.max_input_tokens == 8000


def test_engines_share_provider() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [{"id": "p", "kind": "openai", "base_url": "http://x"}],
            "engines": [
                {"id": "a", "provider": "p", "model": "m1"},
                {"id": "b", "provider": "p", "model": "m2"},
            ],
        }
    )
    assert config.resolved("a").provider_id == "p"  # type: ignore[union-attr]
    assert config.resolved("b").provider_id == "p"  # type: ignore[union-attr]


def test_unknown_provider_reference_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown provider"):
        AppConfig.model_validate({"engines": [{"id": "a", "provider": "ghost"}]})


def test_save_config_round_trips(tmp_path: Path) -> None:
    config = AppConfig.model_validate(
        {
            "providers": [{"id": "p", "kind": "openai", "base_url": "http://x"}],
            "engines": [{"id": "a", "provider": "p", "model": "m1"}],
            "routing": {"chapter": ["a"], "short_text": ["a"]},
        }
    )
    path = tmp_path / "config.yml"
    save_config(config, path)
    loaded = load_config(path)
    assert loaded == config


def test_missing_file_yields_builtin_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.yml")
    engine_ids = {e.id for e in config.engines}
    assert "zai-glm-flash" in engine_ids
    # Every default engine is routed somewhere, and lanes validate.
    routed = set(config.routing.chapter) | set(config.routing.short_text)
    assert engine_ids == routed


def test_default_config_engines_need_keys() -> None:
    # Fresh defaults ship no keys: only the keyless lanes (Bing via Edge's
    # keyless auth, and local NLLB) are available — no API engine can fire
    # accidentally. Setting a provider's key remotely lights up its engines.
    config = load_config(Path("/nonexistent/config.yml"))
    available = [r.id for r in config.resolved_engines() if is_available(r)]
    assert available == ["bing", "nllb"]
    provider = config.provider("zai")
    assert provider is not None
    provider.api_key = "k"
    assert [r.id for r in config.resolved_engines() if is_available(r)] == [
        "zai-glm-flash",
        "bing",
        "nllb",
    ]
    # NLLB is the last lane everywhere: API engines always take priority.
    assert config.routing.chapter[-1] == "nllb"
    assert config.routing.short_text[-1] == "nllb"


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


def test_engine_unavailable_without_key() -> None:
    data = {"engines": [{"id": "a", "kind": "openai", "base_url": "http://x"}]}
    config = AppConfig.model_validate(data)
    resolved = config.resolved("a")
    assert resolved is not None
    assert is_available(resolved) is False

    provider = config.provider("a")
    assert provider is not None
    provider.api_key = "secret"
    resolved = config.resolved("a")
    assert resolved is not None
    assert is_available(resolved) is True

    keyless = AppConfig.model_validate(
        {
            "engines": [
                {
                    "id": "a",
                    "kind": "openai",
                    "base_url": "http://x",
                    "requires_key": False,
                }
            ]
        }
    )
    resolved = keyless.resolved("a")
    assert resolved is not None
    assert is_available(resolved) is True
