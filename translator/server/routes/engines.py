"""Engines: live status and CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, model_validator

from ...config import LANE_NAMES, AppConfig, EngineConfig
from ...config.legacy import hoist_engine_settings
from ...engines import (
    EngineStatus,
    capabilities_for,
    engine_class,
    engine_settings_model,
    is_available,
    resolve_all,
)
from ...errors import ApiError
from ..deps import ConfigDep, RouterDep, StoreDep
from ..dto import EngineCapabilitiesInfo, EngineInfo, EnginesResponse
from ..editing import apply_edit, merge_patch
from ..secrets import redact_engine, resolve_entry_secrets

router = APIRouter(tags=["engines"])


class EnginePatch(BaseModel):
    provider: str | None = None
    enabled: bool | None = None
    settings: dict[str, Any] | None = None

    _hoist = model_validator(mode="before")(hoist_engine_settings)


@router.get("/engines")
def list_engines(config: ConfigDep, engine_router: RouterDep) -> EnginesResponse:
    infos = []
    for resolved in resolve_all(config):
        caps = capabilities_for(resolved)
        status = engine_router.status(resolved.id) or EngineStatus.DISABLED
        slots = engine_router.concurrency(resolved.id)
        infos.append(
            EngineInfo(
                id=resolved.id,
                provider=resolved.provider_id,
                kind=resolved.kind,
                model=engine_class(resolved.kind).display_model(resolved),
                enabled=is_available(resolved),
                capabilities=EngineCapabilitiesInfo(
                    html=caps.html.value,
                    glossary=caps.glossary,
                    max_input_tokens=caps.max_input_tokens,
                    source_langs=caps.source_langs,
                    target_langs=caps.target_langs,
                ),
                status=status.value,
                retry_at=engine_router.retry_at(resolved.id),
                slots_free=slots[0] if slots else None,
                slots_total=slots[1] if slots else None,
            )
        )
    return EnginesResponse(engines=infos)


@router.post("/engines", status_code=201)
async def create_engine(payload: EngineConfig, store: StoreDep) -> EngineConfig:
    if store.config.engine(payload.id) is not None:
        raise ApiError(409, "engine_exists", f"engine {payload.id!r} exists")
    # A new engine has no stored secrets, so placeholders are dropped.
    entry = resolve_entry_secrets(payload.model_dump(), None)
    new_config = await apply_edit(store, lambda data: data["engines"].append(entry))
    created = new_config.engine(payload.id)
    assert created is not None
    return _redacted(new_config, created)


@router.patch("/engines/{engine_id:path}")
async def update_engine(
    engine_id: str, payload: EnginePatch, store: StoreDep
) -> EngineConfig:
    stored = store.config.engine(engine_id)
    if stored is None:
        raise ApiError(404, "not_found", f"unknown engine {engine_id!r}")
    changes = resolve_entry_secrets(payload.model_dump(exclude_unset=True), stored)
    keep = _surviving_settings(store.config, stored, changes.get("provider"))

    def edit(data: dict[str, Any]) -> None:
        for entry in data["engines"]:
            if entry["id"] == engine_id:
                merge_patch(entry, changes, keep=keep)

    new_config = await apply_edit(store, edit)
    updated = new_config.engine(engine_id)
    assert updated is not None
    return _redacted(new_config, updated)


def _surviving_settings(
    config: AppConfig, stored: EngineConfig, target: str | None
) -> set[str] | None:
    """Settings keys that survive a move to ``target``, or ``None`` for "all".

    An engine's settings model comes from its *provider's* kind, so moving it
    across kinds retires the keys the new one does not declare. An unknown
    ``target`` is left to whole-config validation to report.
    """
    if target is None or target == stored.provider:
        return None
    old, new = config.provider(stored.provider), config.provider(target)
    if old is None or new is None or old.kind == new.kind:
        return None
    return set(engine_settings_model(new.kind).model_fields)


def _redacted(config: AppConfig, engine: EngineConfig) -> EngineConfig:
    provider = config.provider(engine.provider)
    assert provider is not None
    return redact_engine(engine, provider.kind)


@router.delete("/engines/{engine_id:path}", status_code=204)
async def delete_engine(engine_id: str, store: StoreDep) -> Response:
    """Remove an engine; it is also stripped from all routing lanes."""
    if store.config.engine(engine_id) is None:
        raise ApiError(404, "not_found", f"unknown engine {engine_id!r}")

    def edit(data: dict[str, Any]) -> None:
        data["engines"] = [e for e in data["engines"] if e["id"] != engine_id]
        for lane in LANE_NAMES:
            data["routing"][lane] = [i for i in data["routing"][lane] if i != engine_id]

    await apply_edit(store, edit)
    return Response(status_code=204)
