from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from translator.config import AppConfig, build_overlay, load_config, save_config
from translator.engines import is_available


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


def test_sparse_overlay_merges_defaults(tmp_path: Path) -> None:
    # A file listing only one provider key still gets every default engine.
    path = tmp_path / "config.yml"
    path.write_text("providers:\n  - id: zai\n    api_key: k\n", encoding="utf-8")
    config = load_config(path)
    assert {e.id for e in config.engines} >= {"zai-glm-flash", "gemini-flash", "nllb"}
    zai = config.provider("zai")
    assert zai is not None
    assert zai.api_key == "k"
    # The default's base_url survives the merge (not clobbered by the overlay).
    assert zai.base_url == "https://api.z.ai/api/paas/v4"
    # Setting the key lights up the engine; defaults for others still apply.
    assert is_available(config.resolved("zai-glm-flash"))  # type: ignore[arg-type]


def test_build_overlay_is_sparse() -> None:
    config = load_config(Path("/nonexistent.yml"))  # built-in defaults
    provider = config.provider("zai")
    assert provider is not None
    provider.api_key = "secret"
    overlay = build_overlay(config)
    # Only the one changed field is written — not the whole default tree.
    assert overlay == {"providers": [{"id": "zai", "api_key": "secret"}]}


def test_overlay_removals_suppress_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        "removed_providers: [groq]\nremoved_engines: [bing]\n", encoding="utf-8"
    )
    config = load_config(path)
    ids = {e.id for e in config.engines}
    assert config.provider("groq") is None
    # groq's engines go with the removed provider; bing is removed directly.
    assert {"groq-oss", "groq-llama", "bing"}.isdisjoint(ids)
    # Removed engines are pruned from the (default) routing lanes too.
    assert "bing" not in config.routing.chapter
    assert "groq-oss" not in config.routing.short_text


def test_removals_round_trip_through_save(tmp_path: Path) -> None:
    config = load_config(Path("/nonexistent.yml"))  # built-in defaults
    config.engines = [e for e in config.engines if e.id != "baidu"]
    config.providers = [p for p in config.providers if p.id != "baidu"]
    config.routing.chapter = [i for i in config.routing.chapter if i != "baidu"]
    config.routing.short_text = [i for i in config.routing.short_text if i != "baidu"]
    path = tmp_path / "config.yml"
    save_config(config, path)
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved.get("removed_providers") == ["baidu"]
    assert "baidu" in saved.get("removed_engines", [])
    reloaded = load_config(path)
    assert reloaded.provider("baidu") is None
    assert reloaded.engine("baidu") is None
    # Everything else still merges in from defaults.
    assert reloaded.provider("zai") is not None


def test_legacy_flat_config_skips_default_merge(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        "engines:\n  - id: solo\n    kind: openai\n    base_url: http://x\n"
        "    requires_key: false\nrouting:\n  chapter: [solo]\n",
        encoding="utf-8",
    )
    config = load_config(path)
    # Legacy flat files load standalone — defaults are NOT merged in.
    assert {e.id for e in config.engines} == {"solo"}


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
