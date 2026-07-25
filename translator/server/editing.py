"""Editing the live config from the API.

Every mutation follows the same shape: dump the live config, change the one
thing the route is about, revalidate the result *as a whole*, then apply it
atomically through the store (which also persists it). Routes describe the
edit; this module owns the transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from ..config import AppConfig
from ..core.store import ConfigStore
from ..engines import validate_config
from ..errors import ApiError


def validated_config(data: dict[str, Any]) -> AppConfig:
    """Revalidate a candidate config, reporting the first problem as a 422.

    A whole-config check is what catches cross-entry breakage — an engine
    pointing at a provider the edit removed, a lane naming a deleted engine.
    The per-kind ``settings`` check runs here too, so a bad kind-specific field
    is a 422 like any other invalid edit rather than a 500 from deeper down.
    """
    try:
        config = AppConfig.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(
            422, "invalid_config", f"{first.get('loc')}: {first.get('msg')}"
        ) from exc
    try:
        validate_config(config)
    except ValueError as exc:
        raise ApiError(422, "invalid_config", str(exc)) from exc
    return config


def merge_patch(
    entry: dict[str, Any], changes: dict[str, Any], *, keep: set[str] | None = None
) -> None:
    """Apply a PATCH body to a config entry, merging ``settings`` one level.

    Same depth as the overlay merge: a patch naming one settings key must not
    delete the siblings it did not mention. A key present with an explicit
    ``null`` still writes through, so clearing a credential keeps working.

    ``keep`` bounds which *stored* settings keys survive, for a patch that
    changes which kind's settings model applies: the outgoing kind's keys are
    not fields of the incoming one, so they have to go rather than merge into a
    422 about leftovers the caller never sent.
    """
    settings = changes.get("settings")
    entry.update({k: v for k, v in changes.items() if k != "settings"})
    if settings is None and keep is None:
        return
    merged = dict(entry.get("settings") or {})
    if keep is not None:
        merged = {key: value for key, value in merged.items() if key in keep}
    merged.update(settings or {})
    entry["settings"] = merged


async def apply_edit(
    store: ConfigStore, edit: Callable[[dict[str, Any]], None]
) -> AppConfig:
    """Run ``edit`` over a copy of the live config and apply the result."""
    data = store.config.model_dump()
    edit(data)
    new_config = validated_config(data)
    await store.apply(new_config)
    return new_config
