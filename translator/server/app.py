"""FastAPI application factory.

Importable without side effects — config is only loaded when ``create_app``
runs. The standalone server entry point lives in ``translator.main``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Security
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import HTTPBasic, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

from .. import __version__
from ..config import AppConfig, load_config, resolve_config_path
from ..core import Router, build_router
from ..core.store import ConfigStore
from . import routes
from .handlers import install_error_handlers
from .middleware import ForwardedPrefixMiddleware, limit_body_size

logger = logging.getLogger(__name__)

LOG_LEVEL_ENV = "LOG_LEVEL"

OPENAPI_TAGS = [
    {"name": "translation", "description": "Translate and detect language"},
    {"name": "engines", "description": "Engine status and management"},
    {
        "name": "providers",
        "description": "Provider accounts and API keys (secrets are"
        " write-only: set here, redacted in every response)",
    },
    {"name": "config", "description": "Whole-config, routing, and policy"},
    {"name": "service", "description": "Liveness and readiness"},
]


def configure_logging() -> None:
    """Attach a formatted handler to the app's loggers ($LOG_LEVEL, default
    INFO). No-op when the root logger already has handlers (e.g. pytest)."""
    logging.basicConfig(
        level=os.environ.get(LOG_LEVEL_ENV, "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_store(
    config: AppConfig | None,
    engine_router: Router | None,
    config_path: str | Path | None,
) -> ConfigStore:
    if config is not None:
        resolved_config = config
        persist_path = Path(config_path) if config_path is not None else None
    else:
        persist_path = resolve_config_path(config_path)
        resolved_config = load_config(persist_path)
    return ConfigStore(
        resolved_config,
        engine_router or build_router(resolved_config),
        persist_path,
    )


def create_app(
    config: AppConfig | None = None,
    engine_router: Router | None = None,
    config_path: str | Path | None = None,
    store: ConfigStore | None = None,
    auth: bool = False,
) -> FastAPI:
    """Build the app. When ``config`` is given explicitly (tests), runtime
    config changes are not persisted unless ``config_path`` is also given.

    When ``store`` is given (embedded mode: a host application mounts this
    app next to a ``TranslatorService`` sharing the same store), the caller
    owns the store's lifecycle — the app will not close it. Mounted sub-app
    lifespans never run under Starlette, so nothing here may depend on one.

    ``auth`` declares an HTTPBearer scheme so the docs show an Authorize button
    and clients send a Bearer token; it is not enforced here (the app has no
    user model) — a mounting host is expected to verify the token.
    """
    caller_store = store
    active_store = caller_store or _build_store(config, engine_router, config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if caller_store is None:  # we built it, so we own closing it
            await active_store.close()

    # Declared, not enforced: adds the Authorize button
    dependencies = []
    if auth:
        dependencies += [
            Security(HTTPBasic(auto_error=False)),
            Security(HTTPBearer(auto_error=False)),
        ]

    app = FastAPI(
        title="translator",
        version=__version__,
        lifespan=lifespan,
        dependencies=dependencies,
        openapi_tags=OPENAPI_TAGS,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(ForwardedPrefixMiddleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=limit_body_size)

    app.state.store = active_store
    routes.mount_static(app)
    app.include_router(routes.router)
    install_error_handlers(app)
    return app
