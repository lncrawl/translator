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
from ..errors import ApiError


def validated_config(data: dict[str, Any]) -> AppConfig:
    """Revalidate a candidate config, reporting the first problem as a 422.

    A whole-config check is what catches cross-entry breakage — an engine
    pointing at a provider the edit removed, a lane naming a deleted engine.
    """
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(
            422, "invalid_config", f"{first.get('loc')}: {first.get('msg')}"
        ) from exc


async def apply_edit(
    store: ConfigStore, edit: Callable[[dict[str, Any]], None]
) -> AppConfig:
    """Run ``edit`` over a copy of the live config and apply the result."""
    data = store.config.model_dump()
    edit(data)
    new_config = validated_config(data)
    await store.apply(new_config)
    return new_config
