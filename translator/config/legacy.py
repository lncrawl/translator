"""Support for pre-``settings`` config files. Deletable as a unit.

Everything that understands an older on-disk shape lives here so a future
release can drop the old format by removing this module, its five call sites,
and ``tests/test_legacy_config.py``:

- ``ProviderConfig`` / ``EngineConfig`` — the ``mode="before"`` hooks calling
  :func:`hoist_provider_settings` / :func:`hoist_engine_settings`
- ``AppConfig`` — the ``mode="before"`` hook calling :func:`migrate_flat_engines`
- ``server.routes.providers.ProviderPatch`` — the same provider hook
- ``config.io.load_config`` — the :func:`looks_legacy` branch

Two historical shapes are handled:

1. **Flat engines** (pre-provider): an engine carried ``base_url``/``kind``
   inline instead of referencing a provider. Migrated into an engine plus an
   implicit provider sharing its id.
2. **Flat settings** (pre-``settings``): kind-specific keys sat at the top level
   of a provider or engine entry, with extra provider credentials in an
   ``options`` bag. Hoisted into ``settings``.

The constants below describe those closed formats. They are not a per-kind
ledger — a new kind declares its fields on its ``Engine`` subclass and never
appears here.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Engine fields that flat entries hoisted into the implicit provider.
LEGACY_PROVIDER_FIELDS = (
    "kind",
    "base_url",
    "api_key",
    "options",
    "requires_key",
    "rps",
    "rpm",
    "max_concurrency",
    "monthly_chars",
)

# Top-level keys that are now per-kind settings.
LEGACY_PROVIDER_SETTING_KEYS = (
    "base_url",
    "api_key",
    "requires_key",
    "rps",
    "rpm",
    "max_concurrency",
)
LEGACY_ENGINE_SETTING_KEYS = (
    "model",
    "extra_body",
    "max_input_tokens",
    "chunk_tokens",
    "source_langs",
    "target_langs",
    "failure_policy",
)
# Named provider credentials used to live in a bag; its entries are spliced
# into settings, not nested under an "options" key.
LEGACY_PROVIDER_SETTING_BAGS = ("options",)
# Keys that no longer exist anywhere and are dropped on load.
LEGACY_DROPPED_KEYS = ("monthly_chars",)


def looks_legacy(data: dict[str, Any]) -> bool:
    """A pre-provider flat config: an engine carrying provider-level fields
    inline instead of a ``provider`` reference. Such files predate the overlay
    format and are loaded standalone (defaults not merged)."""
    engines = data.get("engines")
    if not isinstance(engines, list):
        return False
    markers = set(LEGACY_PROVIDER_FIELDS)
    return any(
        isinstance(e, dict) and "provider" not in e and bool(markers & e.keys())
        for e in engines
    )


def migrate_flat_engines(data: dict[str, Any]) -> dict[str, Any]:
    """Flat engine entries become an engine plus an implicit provider."""
    engines = data.get("engines")
    if not isinstance(engines, list):
        return data
    providers = list(data.get("providers") or [])
    migrated = []
    for entry in engines:
        if isinstance(entry, dict) and "provider" not in entry:
            provider: dict[str, Any] = {"id": entry.get("id")}
            for field_name in LEGACY_PROVIDER_FIELDS:
                if field_name in entry:
                    provider[field_name] = entry[field_name]
            providers.append(provider)
            # A denylist, not an allowlist of EngineConfig fields: the engine's
            # own legacy keys (model, extra_body) are not fields any more, and
            # an allowlist would silently drop them before the settings hoist.
            entry = {
                key: value
                for key, value in entry.items()
                if key not in LEGACY_PROVIDER_FIELDS
            }
            entry["provider"] = provider["id"]
        migrated.append(entry)
    return {**data, "providers": providers, "engines": migrated}


def hoist_provider_settings(entry: Any) -> Any:
    """Move a provider entry's flat per-kind keys into ``settings``."""
    return _hoist(
        entry,
        keys=LEGACY_PROVIDER_SETTING_KEYS,
        bags=LEGACY_PROVIDER_SETTING_BAGS,
        what="provider",
    )


def hoist_engine_settings(entry: Any) -> Any:
    """Move an engine entry's flat per-kind keys into ``settings``."""
    return _hoist(entry, keys=LEGACY_ENGINE_SETTING_KEYS, bags=(), what="engine")


def _hoist(
    entry: Any, *, keys: tuple[str, ...], bags: tuple[str, ...], what: str
) -> Any:
    if not isinstance(entry, dict):
        return entry
    moved: dict[str, Any] = {}
    result = dict(entry)
    for bag_name in bags:
        bag = result.pop(bag_name, None)
        if isinstance(bag, dict):
            moved.update(bag)
    for key in keys:
        if key in result:
            moved[key] = result.pop(key)
    for key in LEGACY_DROPPED_KEYS:
        if result.pop(key, None) is not None:
            logger.debug("%s %r: dropping retired key %r", what, entry.get("id"), key)
    if not moved:
        return result
    logger.warning(
        "%s %r: %s are now nested under 'settings'; the flat form is deprecated"
        " and will be removed in a future release",
        what,
        entry.get("id"),
        ", ".join(sorted(moved)),
    )
    # Flat keys win: after the migration they can only come from the user's own
    # file, while a nested value may have been inherited from a default.
    settings = dict(result.get("settings") or {})
    settings.update(moved)
    result["settings"] = settings
    return result
