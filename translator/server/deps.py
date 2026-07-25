"""Request-scoped dependencies.

Every route reaches the live config and router through these, so the
``app.state`` lookup exists in exactly one place.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..config import AppConfig
from ..core import Router
from ..core.store import ConfigStore


def get_store(request: Request) -> ConfigStore:
    store: ConfigStore = request.app.state.store
    return store


StoreDep = Annotated[ConfigStore, Depends(get_store)]


def get_config(store: StoreDep) -> AppConfig:
    return store.config


ConfigDep = Annotated[AppConfig, Depends(get_config)]


def get_router(store: StoreDep) -> Router:
    return store.router


RouterDep = Annotated[Router, Depends(get_router)]
