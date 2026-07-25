"""The whole config: read it, replace it, and edit routing and policy."""

from __future__ import annotations

from typing import Any, get_args

from fastapi import APIRouter

from ...config import AppConfig, EngineKind, FailurePolicy, RoutingConfig
from ...engines import CredentialField, credential_fields
from ..deps import ConfigDep, StoreDep
from ..editing import apply_edit
from ..secrets import redact_config, resolve_config_secrets

router = APIRouter(tags=["config"])


@router.get("/config")
def get_config(config: ConfigDep) -> AppConfig:
    """The live config. Provider secrets are write-only: each stored
    api_key/secret option is replaced by a placeholder, which ``PUT /config``
    accepts back as "keep the stored value"."""
    return redact_config(config)


@router.put("/config")
async def replace_config(payload: AppConfig, store: StoreDep) -> AppConfig:
    """Replace the whole config. Secret placeholders (as returned by
    ``GET /config``) resolve to the currently stored secrets, so a redacted
    config round-trips without touching them. Responses are redacted."""
    resolved = resolve_config_secrets(payload, store.config)
    await store.apply(resolved)
    return redact_config(resolved)


@router.put("/config/failure-policy")
async def update_failure_policy(
    payload: FailurePolicy, store: StoreDep
) -> FailurePolicy:
    def edit(data: dict[str, Any]) -> None:
        data["failure_policy"] = payload.model_dump()

    await apply_edit(store, edit)
    return payload


@router.put("/routing")
async def replace_routing(payload: RoutingConfig, store: StoreDep) -> RoutingConfig:
    def edit(data: dict[str, Any]) -> None:
        data["routing"] = payload.model_dump()

    await apply_edit(store, edit)
    return payload


@router.get("/credential-schema")
def credential_schema() -> dict[str, list[CredentialField]]:
    """Per-kind credential fields, so the dashboard renders the right inputs."""
    return {kind: credential_fields(kind) for kind in get_args(EngineKind)}
