"""Runtime config API: CRUD over providers, engines, and routing.

Every mutation builds a candidate config from the live one, revalidates it as
a whole, then applies it atomically via the ConfigStore (which also persists
it back to the YAML file). The API is unauthenticated by design — the
service is meant for localhost or a private network; don't expose it.

Provider secrets are write-only: they can be set here but every response is
redacted, and the placeholder sent back means "keep the stored value" (see
the ``secrets`` module).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, ValidationError

from .config import (
    AppConfig,
    EngineConfig,
    EngineKind,
    FailurePolicy,
    ProviderConfig,
    RoutingConfig,
)
from .errors import ApiError
from .secrets import (
    redact_config,
    redact_provider,
    resolve_config_secrets,
    resolve_provider_secrets,
)
from .state import ConfigStore

admin_router = APIRouter()


def _store(request: Request) -> ConfigStore:
    store: ConfigStore = request.app.state.store
    return store


def _validated(data: dict[str, Any]) -> AppConfig:
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(
            422, "invalid_config", f"{first.get('loc')}: {first.get('msg')}"
        ) from exc


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


class EnginePatch(BaseModel):
    provider: str | None = None
    model: str | None = None
    enabled: bool | None = None
    max_input_tokens: int | None = Field(default=None, gt=0)
    chunk_tokens: int | None = Field(default=None, gt=0)
    extra_body: dict[str, Any] | None = None


# -- whole config -----------------------------------------------------------


@admin_router.put("/config", tags=["config"])
async def replace_config(payload: AppConfig, request: Request) -> AppConfig:
    """Replace the whole config. Secret placeholders (as returned by
    ``GET /config``) resolve to the currently stored secrets, so a redacted
    config round-trips without touching them. Responses are redacted."""
    store = _store(request)
    resolved = resolve_config_secrets(payload, store.config)
    await store.apply(resolved)
    return redact_config(resolved)


@admin_router.put("/config/failure-policy", tags=["config"])
async def update_failure_policy(
    payload: FailurePolicy, request: Request
) -> FailurePolicy:
    store = _store(request)
    data = store.config.model_dump()
    data["failure_policy"] = payload.model_dump()
    await store.apply(_validated(data))
    return payload


@admin_router.put("/routing", tags=["config"])
async def replace_routing(payload: RoutingConfig, request: Request) -> RoutingConfig:
    store = _store(request)
    data = store.config.model_dump()
    data["routing"] = payload.model_dump()
    await store.apply(_validated(data))
    return payload


# -- providers ----------------------------------------------------------------


@admin_router.post("/providers", status_code=201, tags=["providers"])
async def create_provider(payload: ProviderConfig, request: Request) -> ProviderConfig:
    store = _store(request)
    if store.config.provider(payload.id) is not None:
        raise ApiError(409, "provider_exists", f"provider {payload.id!r} exists")
    data = store.config.model_dump()
    # A new provider has no stored secrets, so placeholders are dropped.
    data["providers"].append(resolve_provider_secrets(payload.model_dump(), None))
    new_config = _validated(data)
    await store.apply(new_config)
    created = new_config.provider(payload.id)
    assert created is not None
    return redact_provider(created)


@admin_router.patch("/providers/{provider_id:path}", tags=["providers"])
async def update_provider(
    provider_id: str, payload: ProviderPatch, request: Request
) -> ProviderConfig:
    store = _store(request)
    stored = store.config.provider(provider_id)
    if stored is None:
        raise ApiError(404, "not_found", f"unknown provider {provider_id!r}")
    data = store.config.model_dump()
    # Placeholder values mean "keep the stored secret" (see secrets module).
    changes = resolve_provider_secrets(payload.model_dump(exclude_unset=True), stored)
    for entry in data["providers"]:
        if entry["id"] == provider_id:
            entry.update(changes)
    new_config = _validated(data)
    await store.apply(new_config)
    updated = new_config.provider(provider_id)
    assert updated is not None
    return redact_provider(updated)


@admin_router.delete(
    "/providers/{provider_id:path}", status_code=204, tags=["providers"]
)
async def delete_provider(provider_id: str, request: Request) -> Response:
    store = _store(request)
    if store.config.provider(provider_id) is None:
        raise ApiError(404, "not_found", f"unknown provider {provider_id!r}")
    used_by = [e.id for e in store.config.engines if e.provider == provider_id]
    if used_by:
        raise ApiError(
            409,
            "provider_in_use",
            f"provider {provider_id!r} is used by engines: {', '.join(used_by)}",
        )
    data = store.config.model_dump()
    data["providers"] = [p for p in data["providers"] if p["id"] != provider_id]
    await store.apply(_validated(data))
    return Response(status_code=204)


# -- engines ------------------------------------------------------------------


@admin_router.post("/engines", status_code=201, tags=["engines"])
async def create_engine(payload: EngineConfig, request: Request) -> EngineConfig:
    store = _store(request)
    if store.config.engine(payload.id) is not None:
        raise ApiError(409, "engine_exists", f"engine {payload.id!r} exists")
    data = store.config.model_dump()
    data["engines"].append(payload.model_dump())
    await store.apply(_validated(data))
    return payload


@admin_router.patch("/engines/{engine_id:path}", tags=["engines"])
async def update_engine(
    engine_id: str, payload: EnginePatch, request: Request
) -> EngineConfig:
    store = _store(request)
    if store.config.engine(engine_id) is None:
        raise ApiError(404, "not_found", f"unknown engine {engine_id!r}")
    data = store.config.model_dump()
    changes = payload.model_dump(exclude_unset=True)
    for entry in data["engines"]:
        if entry["id"] == engine_id:
            entry.update(changes)
    new_config = _validated(data)
    await store.apply(new_config)
    updated = new_config.engine(engine_id)
    assert updated is not None
    return updated


@admin_router.delete("/engines/{engine_id:path}", status_code=204, tags=["engines"])
async def delete_engine(engine_id: str, request: Request) -> Response:
    """Remove an engine; it is also stripped from all routing lanes."""
    store = _store(request)
    if store.config.engine(engine_id) is None:
        raise ApiError(404, "not_found", f"unknown engine {engine_id!r}")
    data = store.config.model_dump()
    data["engines"] = [e for e in data["engines"] if e["id"] != engine_id]
    for lane in ("chapter", "short_text"):
        data["routing"][lane] = [i for i in data["routing"][lane] if i != engine_id]
    await store.apply(_validated(data))
    return Response(status_code=204)
