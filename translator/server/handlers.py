"""Exception handlers: one error envelope for every failure mode."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..errors import ApiError
from .dto import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def install_error_handlers(app: FastAPI) -> None:
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
