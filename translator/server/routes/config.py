"""The whole config: read it, replace it, and edit routing and policy."""

from __future__ import annotations

from typing import Any, get_args

from fastapi import APIRouter
from pydantic import BaseModel

from ...config import (
    LANE_NAMES,
    AppConfig,
    EngineConfig,
    EngineKind,
    FailurePolicy,
    RoutingConfig,
)
from ...engines import (
    EngineSettings,
    ProviderSettings,
    credential_fields,
    engine_class,
)
from ..deps import ConfigDep, StoreDep
from ..dto import ConfigSchema, KindSchema
from ..editing import apply_edit, validated_config
from ..secrets import SECRET_PLACEHOLDER, redact_config, resolve_config_secrets

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
    # Same 422 path as every other mutation; store.apply would raise from
    # deeper down and surface as a 500.
    await store.apply(validated_config(resolved.model_dump()))
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


def _fields_schema(model: type[BaseModel], exclude: set[str]) -> dict[str, Any]:
    """JSON Schema of a config model minus the fields the UI handles itself."""
    schema: dict[str, Any] = model.model_json_schema()
    schema["properties"] = {
        name: prop
        for name, prop in schema.get("properties", {}).items()
        if name not in exclude
    }
    schema["required"] = [r for r in schema.get("required", []) if r not in exclude]
    return schema


@router.get("/schema")
def config_schema() -> ConfigSchema:
    """The editing contract, generated from the models.

    The dashboard builds every provider, engine and policy form from this, so
    adding a field to a kind reaches the UI with no JavaScript change.
    """
    kinds = []
    for kind in get_args(EngineKind):
        cls = engine_class(kind)
        kinds.append(
            KindSchema(
                kind=kind,
                html=cls.HTML.value,
                glossary=cls.GLOSSARY,
                credentials=credential_fields(kind),
                provider_settings=cls.PROVIDER_SETTINGS.model_json_schema(),
                engine_settings=cls.ENGINE_SETTINGS.model_json_schema(),
            )
        )
    return ConfigSchema(
        # Both entries are identity + settings, and the form supplies the
        # identifiers itself. `provider` and `engine` are the shared bases every
        # kind's settings model extends, so the UI can group inherited fields
        # apart from the kind's own; `engine_entry` is what an engine still
        # keeps outside its settings.
        provider=ProviderSettings.model_json_schema(),
        engine=EngineSettings.model_json_schema(),
        engine_entry=_fields_schema(
            EngineConfig,
            {"id", "provider", "settings"},
        ),
        failure_policy=FailurePolicy.model_json_schema(),
        routing=RoutingConfig.model_json_schema(),
        kinds=kinds,
        lanes=list(LANE_NAMES),
        secret_placeholder=SECRET_PLACEHOLDER,
    )
