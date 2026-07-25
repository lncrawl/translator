"""Provider accounts and their credentials.

Secrets are write-only: they can be set here, but every response is redacted
and the placeholder sent back means "keep the stored value" (see ``secrets``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from ...config import EngineKind, ProviderConfig
from ...errors import ApiError
from ..deps import StoreDep
from ..editing import apply_edit
from ..secrets import redact_provider, resolve_provider_secrets

router = APIRouter(tags=["providers"])


class ProviderPatch(BaseModel):
    kind: EngineKind | None = None
    base_url: str | None = None
    api_key: str | None = None
    options: dict[str, str] | None = None
    requires_key: bool | None = None
    rps: float | None = Field(default=None, gt=0)
    rpm: float | None = Field(default=None, gt=0)
    max_concurrency: int | None = Field(default=None, ge=1)
    monthly_chars: int | None = Field(default=None, gt=0)


@router.post("/providers", status_code=201)
async def create_provider(payload: ProviderConfig, store: StoreDep) -> ProviderConfig:
    if store.config.provider(payload.id) is not None:
        raise ApiError(409, "provider_exists", f"provider {payload.id!r} exists")
    # A new provider has no stored secrets, so placeholders are dropped.
    entry = resolve_provider_secrets(payload.model_dump(), None)
    new_config = await apply_edit(store, lambda data: data["providers"].append(entry))
    created = new_config.provider(payload.id)
    assert created is not None
    return redact_provider(created)


@router.patch("/providers/{provider_id:path}")
async def update_provider(
    provider_id: str, payload: ProviderPatch, store: StoreDep
) -> ProviderConfig:
    stored = store.config.provider(provider_id)
    if stored is None:
        raise ApiError(404, "not_found", f"unknown provider {provider_id!r}")
    # Placeholder values mean "keep the stored secret" (see secrets module).
    changes = resolve_provider_secrets(payload.model_dump(exclude_unset=True), stored)

    def edit(data: dict[str, Any]) -> None:
        for entry in data["providers"]:
            if entry["id"] == provider_id:
                entry.update(changes)

    updated = (await apply_edit(store, edit)).provider(provider_id)
    assert updated is not None
    return redact_provider(updated)


@router.delete("/providers/{provider_id:path}", status_code=204)
async def delete_provider(provider_id: str, store: StoreDep) -> Response:
    if store.config.provider(provider_id) is None:
        raise ApiError(404, "not_found", f"unknown provider {provider_id!r}")
    used_by = [e.id for e in store.config.engines if e.provider == provider_id]
    if used_by:
        raise ApiError(
            409,
            "provider_in_use",
            f"provider {provider_id!r} is used by engines: {', '.join(used_by)}",
        )

    def edit(data: dict[str, Any]) -> None:
        data["providers"] = [p for p in data["providers"] if p["id"] != provider_id]

    await apply_edit(store, edit)
    return Response(status_code=204)
