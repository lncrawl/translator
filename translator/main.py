"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from . import __version__
from .admin import admin_router
from .api import STATIC_DIR, health_router, router
from .config import AppConfig, load_config, resolve_config_path
from .errors import ApiError
from .router import Router
from .schemas import ErrorDetail, ErrorResponse
from .state import ConfigStore, build_router

logger = logging.getLogger(__name__)

LOG_LEVEL_ENV = "LOG_LEVEL"

# Reject request bodies larger than this before parsing them. Generous
# headroom over the largest valid payload (1M chars of HTML + glossary).
MAX_BODY_BYTES = 10 * 1024 * 1024


def configure_logging() -> None:
    """Attach a formatted handler to the app's loggers ($LOG_LEVEL, default
    INFO). No-op when the root logger already has handlers (e.g. pytest)."""
    logging.basicConfig(
        level=os.environ.get(LOG_LEVEL_ENV, "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_app(
    config: AppConfig | None = None,
    engine_router: Router | None = None,
    config_path: str | Path | None = None,
) -> FastAPI:
    """Build the app. When ``config`` is given explicitly (tests), runtime
    config changes are not persisted unless ``config_path`` is also given."""
    configure_logging()
    if config is not None:
        resolved_config = config
        persist_path = Path(config_path) if config_path is not None else None
    else:
        persist_path = resolve_config_path(config_path)
        resolved_config = load_config(persist_path)
    resolved_router = engine_router or build_router(resolved_config)
    store = ConfigStore(resolved_config, resolved_router, persist_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await store.close()

    app = FastAPI(
        title="translator",
        version=__version__,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "translation", "description": "Translate and detect language"},
            {"name": "engines", "description": "Engine status and management"},
            {"name": "providers", "description": "Provider accounts and API keys"},
            {"name": "config", "description": "Whole-config, routing, and policy"},
            {"name": "service", "description": "Liveness and readiness"},
        ],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def limit_body_size(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            length = 0  # malformed header; the server rejects it downstream
        if length > MAX_BODY_BYTES:
            body = ErrorResponse(
                error=ErrorDetail(
                    code="payload_too_large",
                    message=f"request body exceeds {MAX_BODY_BYTES} bytes",
                )
            )
            return JSONResponse(
                status_code=413, content=body.model_dump(exclude_none=True)
            )
        return await call_next(request)

    app.state.store = store
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health_router)
    app.include_router(router)
    app.include_router(admin_router)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                retry_after_seconds=exc.retry_after_seconds,
            )
        )
        headers = {}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(exc.retry_after_seconds)
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(exclude_none=True),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Keep the error envelope consistent and the details out of responses.
        logger.exception(
            "unhandled error on %s %s", request.method, request.url.path, exc_info=exc
        )
        body = ErrorResponse(
            error=ErrorDetail(code="internal_error", message="internal server error")
        )
        return JSONResponse(status_code=500, content=body.model_dump(exclude_none=True))

    return app


app = create_app()
