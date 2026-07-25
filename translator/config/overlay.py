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
from collections.abc import Sequence
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


def _merge_section(
    defaults: dict[str, Any],
    overlay: dict[str, Any],
    section: str,
    self_standing: str,
) -> list[dict[str, Any]]:
    """Merge one ``providers``/``engines`` section: patch the defaults by id,
    then append the overlay-only entries.

    An overlay-only entry is either a self-standing one — recognized by
    carrying ``self_standing`` (a provider declares its ``kind``, an engine its
    ``provider``) — or a sparse patch whose default has since been removed,
    leaving nothing to patch. Drop the latter rather than failing the whole
    config to load.
    """
    removed = set(overlay.get(f"removed_{section}") or [])
    patches = _by_id(overlay.get(section))
    merged: list[dict[str, Any]] = []
    for base in defaults.get(section) or []:
        # Popping leaves `patches` holding exactly the overlay-only entries.
        patch = patches.pop(base["id"], {})
        if base["id"] not in removed:
            merged.append(_merge_entry(base, patch))
    for entry_id, entry in patches.items():
        if entry_id in removed:
            continue
        if self_standing not in entry:
            logger.warning(
                "dropping %s %r: patch with no matching default"
                " (stale overlay for a removed default?)",
                section[:-1],
                entry_id,
            )
            continue
        merged.append(entry)
    return merged


def apply_overlay(defaults: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge a sparse ``overlay`` onto ``defaults`` by id (overlay fields win).

    Defaults keep their order; overlay-only entries are appended. Ids in
    ``removed_providers``/``removed_engines`` drop the matching default, and a
    removed provider takes its engines with it. Routing lanes fall back to the
    default lane when the overlay omits them, then are pruned to engines that
    survived the merge.
    """
    providers = _merge_section(defaults, overlay, "providers", "kind")
    provider_ids = {p["id"] for p in providers}
    engines = [
        e
        for e in _merge_section(defaults, overlay, "engines", "provider")
        if e.get("provider") in provider_ids  # a removed provider takes its engines
    ]
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


def _custom(model: BaseModel, keep: str | None) -> dict[str, Any]:
    """A self-standing entry, written in full minus inert defaults.

    ``keep`` forces one field back in: a provider's ``kind`` has a default, so
    ``exclude_defaults`` would strip it from an openai provider — and its
    presence is exactly what tells the merge this is a self-standing entry
    rather than a patch for a vanished default.
    """
    entry = model.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    if keep is not None:
        entry[keep] = model.model_dump(mode="json")[keep]
    return entry


def _section_overlay(
    section: str,
    current: Sequence[Any],
    defaults: Sequence[Any],
    keep: str | None = None,
) -> dict[str, Any]:
    """The sparse form of one section: a diff per changed default, a full entry
    per custom one, nothing for a default left untouched, and the ids of the
    defaults this config dropped."""
    by_id = {entry.id: entry for entry in defaults}
    live = {entry.id for entry in current}
    diffs: list[dict[str, Any]] = []
    for entry in current:
        base = by_id.get(entry.id)
        if base is None:
            diffs.append(_custom(entry, keep))
            continue
        diff = _diff_entry(entry, base)
        if len(diff) > 1:  # more than just the id — something changed
            diffs.append(diff)
    out: dict[str, Any] = {section: diffs} if diffs else {}
    removed = [entry_id for entry_id in by_id if entry_id not in live]
    if removed:
        out[f"removed_{section}"] = removed
    return out


def build_overlay(config: AppConfig) -> dict[str, Any]:
    """The sparse overlay for ``config`` relative to the built-in defaults:
    only changed/custom entries, derived removals, and non-default routing."""
    defaults = AppConfig.model_validate(DEFAULT_CONFIG)
    overlay: dict[str, Any] = {
        **_section_overlay("providers", config.providers, defaults.providers, "kind"),
        **_section_overlay("engines", config.engines, defaults.engines),
    }

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
