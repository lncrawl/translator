"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .api import health_router, router
from .config import AppConfig, load_config
from .engines import build_engine
from .errors import ApiError
from .router import Router
from .schemas import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def build_router(config: AppConfig) -> Router:
    engines = []
    for engine_config in config.engines:
        if not engine_config.enabled:
            logger.warning(
                "engine %s disabled: $%s not set",
                engine_config.id,
                engine_config.api_key_env,
            )
            continue
        engines.append(build_engine(engine_config))
    return Router(engines, config)


def create_app(
    config: AppConfig | None = None, engine_router: Router | None = None
) -> FastAPI:
    resolved_config = config if config is not None else load_config()
    resolved_router = engine_router or build_router(resolved_config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await resolved_router.close()

    app = FastAPI(title="translator", version=__version__, lifespan=lifespan)
    app.state.config = resolved_config
    app.state.router = resolved_router
    app.include_router(health_router)
    app.include_router(router)

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

    return app


app = create_app()
