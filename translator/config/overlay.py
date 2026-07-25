"""The sparse-overlay format: merging a config file onto the built-in defaults.

The config file is a *sparse overlay* on the built-in defaults, not a full
snapshot: it carries only what differs (api keys, custom providers/engines,
routing tweaks) plus explicit removals. Defaults always come from code and
merge underneath by id, so new or changed defaults reach existing installs
without the file going stale. :func:`apply_overlay` merges on load;
:func:`build_overlay` diffs on save.

Merge depth is exactly one level into ``settings`` — and the diff matches it
key by key. The two must agree or ``build_overlay ∘ apply_overlay`` stops
round-tripping: a key the diff emits as ``None`` is one the user removed from a
default, so the merge drops it instead of passing a null to the kind's model.
Values *inside* ``settings`` (``extra_body`` included) replace
wholesale: they are opaque values, not namespaces, and deep-merging them would
leave no way to remove a key a default had set.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from .defaults import DEFAULT_CONFIG
from .models import LANE_NAMES, AppConfig

logger = logging.getLogger(__name__)


def _by_id(entries: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
    return out


def _merge_entry(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Overlay one entry onto its default, merging ``settings`` one level.

    A settings key worth ``None`` is a *removal*, not a value: that is how
    :func:`_diff_settings` records a key the user dropped from a default, and
    keeping it would hand the kind's model a null where its field wants an int.
    Dropped means the field's own default applies, which is what the user had.
    """
    merged = {**base, **patch}
    if "settings" in base or "settings" in patch:
        settings = {
            **(base.get("settings") or {}),
            **(patch.get("settings") or {}),
        }
        merged["settings"] = {k: v for k, v in settings.items() if v is not None}
    return merged


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
        merged.append(_merge_entry(base, patches.get(pid, {})))
        seen.add(pid)
    # An overlay-only provider is either a self-standing custom entry, which
    # declares its ``kind``, or a sparse patch whose default has since been
    # removed — leaving nothing to patch. Drop the latter rather than failing
    # the whole config to load. This mirrors the rule engines already live
    # under below, where a patch with no surviving provider is dropped.
    for pid, entry in patches.items():
        if pid in seen or pid in removed:
            continue
        if "kind" not in entry:
            logger.warning(
                "dropping provider %r: patch with no matching default"
                " (stale overlay for a removed default?)",
                pid,
            )
            continue
        merged.append(entry)
        seen.add(pid)
    return merged


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
        merged.append(_merge_entry(base, patches.get(eid, {})))
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


def _diff_settings(cur: dict[str, Any], bas: dict[str, Any]) -> dict[str, Any]:
    """Settings keys that differ, over the union of both key sets.

    A key the user removed is emitted as ``None`` rather than omitted —
    omitting it would let the default merge straight back in on load.
    """
    diff = {key: value for key, value in cur.items() if bas.get(key) != value}
    diff.update({key: None for key in bas if key not in cur})
    return diff


def _diff_entry(current: BaseModel, base: BaseModel) -> dict[str, Any]:
    """Fields of ``current`` that differ from ``base``, always keeping ``id``."""
    cur = current.model_dump(mode="json")
    bas = base.model_dump(mode="json")
    diff: dict[str, Any] = {"id": cur["id"]}
    for key, value in cur.items():
        if key == "id":
            continue
        if key == "settings":
            settings = _diff_settings(value or {}, bas.get("settings") or {})
            if settings:
                diff["settings"] = settings
            continue
        if bas.get(key) != value:
            diff[key] = value
    return diff


def _custom(model: BaseModel) -> dict[str, Any]:
    """A self-standing entry, written in full minus inert defaults."""
    return model.model_dump(mode="json", exclude_defaults=True, exclude_none=True)


def _custom_provider(provider: BaseModel) -> dict[str, Any]:
    """A custom provider always keeps its ``kind``.

    ``kind`` has a default, so ``exclude_defaults`` would strip it from an
    openai provider — and its presence is exactly what tells the merge this is
    a self-standing entry rather than a patch for a vanished default.
    """
    entry = _custom(provider)
    entry["kind"] = provider.model_dump(mode="json")["kind"]
    return entry


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
            provider_diffs.append(_custom_provider(provider))
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
