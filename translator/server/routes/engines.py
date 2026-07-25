"""Engines: live status and CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from ...config import EngineConfig
from ...engines import EngineStatus, capabilities_for, is_available
from ...errors import ApiError
from ..deps import ConfigDep, RouterDep, StoreDep
from ..dto import EngineCapabilitiesInfo, EngineInfo, EnginesResponse
from ..editing import apply_edit

router = APIRouter(tags=["engines"])


class EnginePatch(BaseModel):
    provider: str | None = None
    model: str | None = None
    enabled: bool | None = None
    max_input_tokens: int | None = Field(default=None, gt=0)
    chunk_tokens: int | None = Field(default=None, gt=0)
    extra_body: dict[str, Any] | None = None


@router.get("/engines")
def list_engines(config: ConfigDep, engine_router: RouterDep) -> EnginesResponse:
    infos = []
    for resolved in config.resolved_engines():
        caps = capabilities_for(resolved)
        status = engine_router.status(resolved.id) or EngineStatus.DISABLED
        slots = engine_router.concurrency(resolved.id)
        infos.append(
            EngineInfo(
                id=resolved.id,
                provider=resolved.provider_id,
                kind=resolved.kind,
                model=resolved.model,
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
    await apply_edit(store, lambda data: data["engines"].append(payload.model_dump()))
    return payload


@router.patch("/engines/{engine_id:path}")
async def update_engine(
    engine_id: str, payload: EnginePatch, store: StoreDep
) -> EngineConfig:
    if store.config.engine(engine_id) is None:
        raise ApiError(404, "not_found", f"unknown engine {engine_id!r}")
    changes = payload.model_dump(exclude_unset=True)

    def edit(data: dict[str, Any]) -> None:
        for entry in data["engines"]:
            if entry["id"] == engine_id:
                entry.update(changes)

    updated = (await apply_edit(store, edit)).engine(engine_id)
    assert updated is not None
    return updated


@router.delete("/engines/{engine_id:path}", status_code=204)
async def delete_engine(engine_id: str, store: StoreDep) -> Response:
    """Remove an engine; it is also stripped from all routing lanes."""
    if store.config.engine(engine_id) is None:
        raise ApiError(404, "not_found", f"unknown engine {engine_id!r}")

    def edit(data: dict[str, Any]) -> None:
        data["engines"] = [e for e in data["engines"] if e["id"] != engine_id]
        for lane in ("chapter", "short_text"):
            data["routing"][lane] = [i for i in data["routing"][lane] if i != engine_id]

    await apply_edit(store, edit)
    return Response(status_code=204)
