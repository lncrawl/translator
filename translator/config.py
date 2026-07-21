"""Configuration loading: a YAML file for engines/routing, env vars for secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_CONFIG_PATH = "config.yml"
CONFIG_PATH_ENV = "TRANSLATOR_CONFIG"

EngineKind = Literal["openai", "deepl"]


class EngineConfig(BaseModel):
    id: str
    kind: EngineKind
    base_url: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    rps: float | None = Field(default=None, gt=0)
    rpm: float | None = Field(default=None, gt=0)
    max_concurrency: int = Field(default=1, ge=1)
    max_input_tokens: int | None = Field(default=None, gt=0)
    monthly_chars: int | None = Field(default=None, gt=0)

    @property
    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env) or None

    @property
    def enabled(self) -> bool:
        """An engine is disabled when it declares a key env that is not set."""
        if self.api_key_env:
            return self.api_key is not None
        return True


class RoutingConfig(BaseModel):
    chapter: list[str] = []
    short_text: list[str] = []


class AppConfig(BaseModel):
    engines: list[EngineConfig] = []
    routing: RoutingConfig = RoutingConfig()

    @model_validator(mode="after")
    def _validate_references(self) -> AppConfig:
        ids = [e.id for e in self.engines]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate engine ids in config")
        known = set(ids)
        for lane_name in ("chapter", "short_text"):
            for engine_id in getattr(self.routing, lane_name):
                if engine_id not in known:
                    raise ValueError(
                        f"routing.{lane_name} references unknown engine {engine_id!r}"
                    )
        return self

    def engine(self, engine_id: str) -> EngineConfig | None:
        return next((e for e in self.engines if e.id == engine_id), None)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from ``path``, $TRANSLATOR_CONFIG, or ./config.yml.

    A missing file yields an empty config (no engines) so the service can
    still boot and report itself unconfigured via /health and /engines.
    """
    resolved = Path(path or os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)
    if not resolved.exists():
        return AppConfig()
    with resolved.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    return AppConfig.model_validate(data)
