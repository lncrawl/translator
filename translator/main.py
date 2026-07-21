"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from . import __version__
from .api import health_router, router
from .config import AppConfig, load_config
from .engines import build_engine
from .errors import ApiError
from .router import Router
from .schemas import ErrorDetail, ErrorResponse

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
    configure_logging()
    resolved_config = config if config is not None else load_config()
    resolved_router = engine_router or build_router(resolved_config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await resolved_router.close()

    app = FastAPI(title="translator", version=__version__, lifespan=lifespan)
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
