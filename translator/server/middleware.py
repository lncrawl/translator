"""HTTP middleware: reverse-proxy prefixes and a request body ceiling."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .dto import ErrorDetail, ErrorResponse

# Reject request bodies larger than this before parsing them. Generous
# headroom over the largest valid payload (1M chars of HTML + glossary).
MAX_BODY_BYTES = 10 * 1024 * 1024


class ForwardedPrefixMiddleware:
    """Honor ``X-Forwarded-Prefix`` from a mounting reverse proxy so FastAPI's own
    docs/OpenAPI links resolve under the prefix. The SPA relies on a ``<base href>``
    the proxy injects, so this is only for the framework-generated pages."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            prefix = Headers(scope=scope).get("x-forwarded-prefix")
            if prefix:
                scope["root_path"] = prefix.rstrip("/")
        await self.app(scope, receive, send)


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
        return JSONResponse(status_code=413, content=body.model_dump(exclude_none=True))
    return await call_next(request)
