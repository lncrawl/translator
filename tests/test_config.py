from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from translator.config import AppConfig, build_overlay, load_config, save_config
from translator.engines import (
    engine_class,
    is_available,
    resolve,
    resolve_all,
    validate_config,
)


def openai_provider(provider_id: str, **settings: object) -> dict[str, object]:
    return {
        "id": provider_id,
        "kind": "openai",
        "settings": {"base_url": "http://x/v1", **settings},
    }


def test_engines_share_provider() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [openai_provider("p")],
            "engines": [
                {"id": "a", "provider": "p", "settings": {"model": "m1"}},
                {"id": "b", "provider": "p", "settings": {"model": "m2"}},
            ],
        }
    )
    assert resolve(config, "a").provider_id == "p"  # type: ignore[union-attr]
    assert resolve(config, "b").provider_id == "p"  # type: ignore[union-attr]


def test_unknown_provider_reference_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown provider"):
        AppConfig.model_validate({"engines": [{"id": "a", "provider": "ghost"}]})


def test_save_config_round_trips(tmp_path: Path) -> None:
    config = AppConfig.model_validate(
        {
            "providers": [openai_provider("p")],
            "engines": [{"id": "a", "provider": "p", "settings": {"model": "m1"}}],
            "routing": {"chapter": ["a"], "short_text": ["a"]},
        }
    )
    path = tmp_path / "config.yml"
    save_config(config, path)
    loaded = load_config(path)
    assert loaded == config


def test_custom_provider_keeps_its_kind_when_saved(tmp_path: Path) -> None:
    # `kind` has a default, so exclude_defaults would drop it — but its
    # presence is what marks the entry self-standing rather than a patch for a
    # default that no longer exists.
    config = AppConfig.model_validate(
        {
            "providers": [openai_provider("mine")],
            "engines": [{"id": "a", "provider": "mine"}],
        }
    )
    path = tmp_path / "config.yml"
    save_config(config, path)
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["providers"][0]["kind"] == "openai"
    assert load_config(path).provider("mine") is not None


def test_sparse_patch_preserves_sibling_settings(tmp_path: Path) -> None:
    # The merge is one level deep into `settings`: a patch that sets only the
    # api_key must not wipe the default's base_url. Getting this wrong drops
    # the provider, its engines, and its routing entries — silently.
    path = tmp_path / "config.yml"
    path.write_text(
        "providers:\n  - id: gemini\n    settings:\n      api_key: k\n",
        encoding="utf-8",
    )
    config = load_config(path)
    gemini = config.provider("gemini")
    assert gemini is not None
    assert gemini.settings["api_key"] == "k"
    assert (
        gemini.settings["base_url"]
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert {e.id for e in config.engines} >= {
        "gemini-flash-latest",
        "groq-oss-120b",
        "bing",
    }
    assert is_available(resolve(config, "gemini-flash-latest"))  # type: ignore[arg-type]


def test_dropping_a_default_settings_key_round_trips(tmp_path: Path) -> None:
    # Not setting a key the default sets is a valid config, so the file it saves
    # must load again: the diff records the drop as a null, and the merge has to
    # read that as "absent" instead of handing the model a null it rejects.
    config = load_config(tmp_path / "missing.yml")
    gemini = config.provider("gemini")
    assert gemini is not None and "max_concurrency" in gemini.settings
    gemini.settings = {
        k: v for k, v in gemini.settings.items() if k != "max_concurrency"
    }

    path = tmp_path / "config.yml"
    save_config(config, path)
    reloaded = load_config(path)
    validate_config(reloaded)
    survivor = reloaded.provider("gemini")
    assert survivor is not None
    assert "max_concurrency" not in survivor.settings
    # The field's own default applies, which is what the dropped key asked for.
    resolved = resolve(reloaded, "gemini-flash-latest")
    assert resolved is not None
    assert resolved.provider_settings.max_concurrency == 1
    assert build_overlay(reloaded) == build_overlay(config)


def test_stale_patch_for_removed_default_is_dropped(tmp_path: Path) -> None:
    # A patch whose default is gone has nothing to patch; it is pruned rather
    # than failing the whole file to load. A custom entry declares its kind.
    path = tmp_path / "config.yml"
    path.write_text(
        "providers:\n"
        "  - id: ghost\n"
        "    settings:\n"
        "      api_key: k\n"
        "  - id: mine\n"
        "    kind: openai\n"
        "    settings:\n"
        "      base_url: http://x/v1\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.provider("ghost") is None
    assert config.provider("mine") is not None


def test_build_overlay_is_sparse() -> None:
    config = load_config(Path("/nonexistent.yml"))  # built-in defaults
    provider = config.provider("gemini")
    assert provider is not None
    provider.settings["api_key"] = "secret"
    overlay = build_overlay(config)
    # Only the one changed settings key is written — not the whole default
    # tree, and not the sibling base_url it inherited.
    assert overlay == {
        "providers": [{"id": "gemini", "settings": {"api_key": "secret"}}]
    }


def test_overlay_removals_suppress_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        "removed_providers: [groq]\nremoved_engines: [bing]\n", encoding="utf-8"
    )
    config = load_config(path)
    ids = {e.id for e in config.engines}
    assert config.provider("groq") is None
    # groq's engine goes with the removed provider; bing is removed directly.
    assert {"groq-oss-120b", "bing"}.isdisjoint(ids)
    # Removed engines are pruned from the (default) routing lanes too.
    assert "bing" not in config.routing.chapter
    assert "groq-oss-120b" not in config.routing.short_text


def test_removals_round_trip_through_save(tmp_path: Path) -> None:
    config = load_config(Path("/nonexistent.yml"))  # built-in defaults
    config.engines = [e for e in config.engines if e.id != "bing"]
    config.providers = [p for p in config.providers if p.id != "bing"]
    config.routing.chapter = [i for i in config.routing.chapter if i != "bing"]
    config.routing.short_text = [i for i in config.routing.short_text if i != "bing"]
    path = tmp_path / "config.yml"
    save_config(config, path)
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved.get("removed_providers") == ["bing"]
    assert "bing" in saved.get("removed_engines", [])
    reloaded = load_config(path)
    assert reloaded.provider("bing") is None
    assert reloaded.engine("bing") is None
    # Everything else still merges in from defaults.
    assert reloaded.provider("gemini") is not None


def test_missing_file_yields_builtin_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.yml")
    engine_ids = {e.id for e in config.engines}
    assert "gemini-flash-latest" in engine_ids
    routed = set(config.routing.chapter) | set(config.routing.short_text)
    # Lanes only reference real engines, and every *enabled* engine is routed.
    # Disabled examples (local-model templates) may sit unrouted until enabled.
    assert routed <= engine_ids
    assert {e.id for e in config.engines if e.enabled} == routed


def test_default_config_engines_need_keys() -> None:
    # Fresh defaults ship no keys: only the keyless Bing lane (via Edge's
    # keyless auth) is available — no API engine can fire accidentally.
    # Setting a provider's key remotely lights up its engines.
    config = load_config(Path("/nonexistent/config.yml"))
    available = [r.id for r in resolve_all(config) if is_available(r)]
    assert available == ["bing"]
    provider = config.provider("gemini")
    assert provider is not None
    provider.settings["api_key"] = "k"
    assert [r.id for r in resolve_all(config) if is_available(r)] == [
        "bing",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
    ]
    # Bing is the default lane, first everywhere.
    assert config.routing.chapter[0] == "bing"
    assert config.routing.short_text[0] == "bing"


def test_unknown_routing_reference_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown engine"):
        AppConfig.model_validate(
            {
                "providers": [openai_provider("p")],
                "engines": [{"id": "a", "provider": "p"}],
                "routing": {"chapter": ["ghost"]},
            }
        )


def test_duplicate_engine_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        AppConfig.model_validate(
            {
                "providers": [openai_provider("p")],
                "engines": [{"id": "a", "provider": "p"}, {"id": "a", "provider": "p"}],
            }
        )


def test_engine_unavailable_without_key() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [openai_provider("p")],
            "engines": [{"id": "a", "provider": "p"}],
        }
    )
    resolved = resolve(config, "a")
    assert resolved is not None
    assert is_available(resolved) is False

    provider = config.provider("p")
    assert provider is not None
    provider.settings["api_key"] = "secret"
    resolved = resolve(config, "a")
    assert resolved is not None
    assert is_available(resolved) is True

    keyless = AppConfig.model_validate(
        {
            "providers": [openai_provider("p", requires_key=False)],
            "engines": [{"id": "a", "provider": "p"}],
        }
    )
    resolved = resolve(keyless, "a")
    assert resolved is not None
    assert is_available(resolved) is True


# -- per-kind settings validation ----------------------------------------------


def test_unknown_settings_key_is_rejected() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [openai_provider("p", nonsense="x")],
            "engines": [{"id": "a", "provider": "p"}],
        }
    )
    with pytest.raises(ValueError, match="nonsense"):
        validate_config(config)


def test_openai_provider_requires_base_url() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [{"id": "p", "kind": "openai", "settings": {"api_key": "k"}}],
            "engines": [{"id": "a", "provider": "p"}],
        }
    )
    with pytest.raises(ValueError, match="base_url"):
        validate_config(config)


def test_settings_of_the_wrong_kind_are_rejected() -> None:
    # `model` is an openai engine setting; a bing engine takes none.
    config = AppConfig.model_validate(
        {
            "providers": [
                {"id": "b", "kind": "bing", "settings": {"requires_key": False}}
            ],
            "engines": [{"id": "a", "provider": "b", "settings": {"model": "x"}}],
        }
    )
    with pytest.raises(ValueError, match="model"):
        validate_config(config)


def test_settings_fields_must_declare_secrecy() -> None:
    # A field that says nothing about secrecy would be returned in plaintext by
    # GET /config. The registry refuses to import rather than leak silently.
    from pydantic import Field

    from translator.engines import ENGINE_CLASSES
    from translator.engines.base import ProviderSettings
    from translator.engines.registry import _undeclared_secrecy

    class Unmarked(ProviderSettings):
        token: str | None = Field(default=None)

    cls = ENGINE_CLASSES["openai"]
    original = cls.PROVIDER_SETTINGS
    try:
        cls.PROVIDER_SETTINGS = Unmarked
        assert _undeclared_secrecy() == ["openai.provider.token"]
    finally:
        cls.PROVIDER_SETTINGS = original
    assert _undeclared_secrecy() == []


def test_kind_declares_its_own_limit_instead_of_clamping() -> None:
    # bing's request cap is a field bound, so asking for more is rejected up
    # front rather than silently reduced at call time.
    config = AppConfig.model_validate(
        {
            "providers": [{"id": "b", "kind": "bing"}],
            "engines": [
                {"id": "a", "provider": "b", "settings": {"max_input_tokens": 999_999}}
            ],
        }
    )
    with pytest.raises(ValueError, match="max_input_tokens"):
        validate_config(config)


def test_kind_declares_its_language_catalog_as_a_default() -> None:
    config = AppConfig.model_validate(
        {
            "providers": [{"id": "bd", "kind": "baidu"}],
            "engines": [{"id": "a", "provider": "bd"}],
        }
    )
    resolved = resolve(config, "a")
    assert resolved is not None
    _, targets = engine_class("baidu").coverage(resolved)
    assert targets is not None and "ja" in targets and "en" in targets
    # An explicit list narrows the catalog rather than being ignored.
    narrowed = AppConfig.model_validate(
        {
            "providers": [{"id": "bd", "kind": "baidu"}],
            "engines": [
                {"id": "a", "provider": "bd", "settings": {"target_langs": ["en"]}}
            ],
        }
    )
    _, targets = engine_class("baidu").coverage(resolve(narrowed, "a"))  # type: ignore[arg-type]
    assert targets == ["en"]
