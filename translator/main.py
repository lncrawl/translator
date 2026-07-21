"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .api import health_router, router
from .config import AppConfig, load_config
from .errors import ApiError
from .schemas import ErrorDetail, ErrorResponse


def create_app(config: AppConfig | None = None) -> FastAPI:
    app = FastAPI(title="translator", version=__version__)
    app.state.config = config if config is not None else load_config()
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
