"""The sparse-overlay format: merging a config file onto the built-in defaults.

The config file is a *sparse overlay* on the built-in defaults, not a full
snapshot: it carries only what differs (api keys, custom providers/engines,
routing tweaks) plus explicit removals. Defaults always come from code and
merge underneath by id, so new or changed defaults reach existing installs
without the file going stale. :func:`apply_overlay` merges on load;
:func:`build_overlay` diffs on save.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from .defaults import DEFAULT_CONFIG
from .models import LANE_NAMES, LEGACY_PROVIDER_FIELDS, AppConfig

logger = logging.getLogger(__name__)


def looks_legacy(data: dict[str, Any]) -> bool:
    """A pre-overlay flat config: an engine carrying provider-level fields
    (base_url/kind/...) inline instead of a ``provider`` reference. Such files
    predate the overlay format and are loaded standalone (defaults not merged)
    for backward compatibility."""
    engines = data.get("engines")
    if not isinstance(engines, list):
        return False
    markers = set(LEGACY_PROVIDER_FIELDS)
    return any(
        isinstance(e, dict) and "provider" not in e and bool(markers & e.keys())
        for e in engines
    )


def _by_id(entries: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
    return out


def _merge_providers(
    defaults: dict[str, Any], overlay: dict[str, Any]
) -> list[dict[str, Any]]:
    removed = set(overlay.get("removed_providers") or [])
    patches = _by_id(overlay.get("providers"))

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for base in defaults.get("providers") or []:
        pid = base["id"]
        if pid in removed:
            continue
        merged.append({**base, **patches.get(pid, {})})
        seen.add(pid)
    for pid, entry in patches.items():
        if pid not in seen and pid not in removed:
            merged.append(entry)
            seen.add(pid)

    # Drop providers that can no longer form a usable account: an openai
    # provider with no base_url is a sparse overlay (e.g. just an api_key) for
    # a default that has since been removed — its base_url is gone with the
    # default. Prune it (and, later, its engines) instead of failing the whole
    # config to load.
    kept: list[dict[str, Any]] = []
    for provider in merged:
        if provider.get("kind", "openai") == "openai" and not provider.get("base_url"):
            logger.warning(
                "dropping provider %r: openai kind without base_url"
                " (stale overlay for a removed default?)",
                provider.get("id"),
            )
            continue
        kept.append(provider)
    return kept


def _merge_engines(
    defaults: dict[str, Any], overlay: dict[str, Any], provider_ids: set[str]
) -> list[dict[str, Any]]:
    removed = set(overlay.get("removed_engines") or [])
    patches = _by_id(overlay.get("engines"))

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for base in defaults.get("engines") or []:
        eid = base["id"]
        if eid in removed:
            continue
        merged.append({**base, **patches.get(eid, {})})
        seen.add(eid)
    for eid, entry in patches.items():
        if eid not in seen and eid not in removed:
            merged.append(entry)
            seen.add(eid)
    return [e for e in merged if e.get("provider") in provider_ids]


def apply_overlay(defaults: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge a sparse ``overlay`` onto ``defaults`` by id (overlay fields win).

    Defaults keep their order; overlay-only entries are appended. Ids in
    ``removed_providers``/``removed_engines`` drop the matching default, and a
    removed provider takes its engines with it. Routing lanes fall back to the
    default lane when the overlay omits them, then are pruned to engines that
    survived the merge.
    """
    providers = _merge_providers(defaults, overlay)
    engines = _merge_engines(defaults, overlay, {p["id"] for p in providers})
    engine_ids = {e["id"] for e in engines}

    overlay_routing = overlay.get("routing") or {}
    default_routing = defaults.get("routing") or {}
    routing: dict[str, list[str]] = {}
    for lane in LANE_NAMES:
        source = (
            overlay_routing[lane]
            if lane in overlay_routing
            else (default_routing.get(lane) or [])
        )
        routing[lane] = [i for i in source if i in engine_ids]

    merged: dict[str, Any] = {
        "providers": providers,
        "engines": engines,
        "routing": routing,
    }
    if "failure_policy" in overlay:
        merged["failure_policy"] = overlay["failure_policy"]
    elif "failure_policy" in defaults:
        merged["failure_policy"] = defaults["failure_policy"]
    return merged


def _diff_entry(current: BaseModel, base: BaseModel) -> dict[str, Any]:
    """Fields of ``current`` that differ from ``base``, always keeping ``id``."""
    cur = current.model_dump(mode="json")
    bas = base.model_dump(mode="json")
    diff: dict[str, Any] = {"id": cur["id"]}
    for key, value in cur.items():
        if key != "id" and bas.get(key) != value:
            diff[key] = value
    return diff


def _custom(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_defaults=True, exclude_none=True)


def build_overlay(config: AppConfig) -> dict[str, Any]:
    """The sparse overlay for ``config`` relative to the built-in defaults:
    only changed/custom entries, derived removals, and non-default routing."""
    defaults = AppConfig.model_validate(DEFAULT_CONFIG)
    default_providers = {p.id: p for p in defaults.providers}
    default_engines = {e.id: e for e in defaults.engines}
    overlay: dict[str, Any] = {}

    provider_diffs: list[dict[str, Any]] = []
    for provider in config.providers:
        base = default_providers.get(provider.id)
        if base is None:
            provider_diffs.append(_custom(provider))
        else:
            diff = _diff_entry(provider, base)
            if len(diff) > 1:  # more than just the id — something changed
                provider_diffs.append(diff)
    if provider_diffs:
        overlay["providers"] = provider_diffs
    removed_providers = [
        pid for pid in default_providers if config.provider(pid) is None
    ]
    if removed_providers:
        overlay["removed_providers"] = removed_providers

    engine_diffs: list[dict[str, Any]] = []
    for engine in config.engines:
        engine_base = default_engines.get(engine.id)
        if engine_base is None:
            engine_diffs.append(_custom(engine))
        else:
            diff = _diff_entry(engine, engine_base)
            if len(diff) > 1:
                engine_diffs.append(diff)
    if engine_diffs:
        overlay["engines"] = engine_diffs
    removed_engines = [eid for eid in default_engines if config.engine(eid) is None]
    if removed_engines:
        overlay["removed_engines"] = removed_engines

    routing: dict[str, list[str]] = {}
    for lane in LANE_NAMES:
        current = getattr(config.routing, lane)
        if current != getattr(defaults.routing, lane):
            routing[lane] = current
    if routing:
        overlay["routing"] = routing

    failure_policy = config.failure_policy.model_dump(exclude_defaults=True)
    if failure_policy:
        overlay["failure_policy"] = failure_policy
    return overlay
