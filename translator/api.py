"""HTTP route handlers."""

from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from . import __version__
from .config import AppConfig
from .detect import detect_language
from .engines import EngineStatus, capabilities_for
from .errors import ApiError
from .router import Router
from .schemas import (
    DetectionResult,
    DetectRequest,
    DetectResponse,
    EngineCapabilitiesInfo,
    EngineInfo,
    EnginesResponse,
    TranslateHtmlRequest,
    TranslateHtmlResponse,
    TranslateTextRequest,
    TranslateTextResponse,
)

AUTH_TOKEN_ENV = "AUTH_TOKEN"


def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token auth, active only when $AUTH_TOKEN is set."""
    token = os.environ.get(AUTH_TOKEN_ENV)
    if not token:
        return
    # Compare as bytes: compare_digest raises TypeError on non-ASCII str.
    expected = f"Bearer {token}".encode()
    provided = (authorization or "").encode("utf-8", errors="replace")
    if not secrets.compare_digest(provided, expected):
        raise ApiError(401, "unauthorized", "missing or invalid bearer token")


def _config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.config
    return config


def _router(request: Request) -> Router:
    engine_router: Router = request.app.state.router
    return engine_router


health_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_auth)])


@health_router.get("/")
def root() -> dict[str, str]:
    return {"service": "translator", "version": __version__, "docs": "/docs"}


@health_router.get("/health")
def health(request: Request) -> dict[str, object]:
    config = _config(request)
    usable = [e.id for e in config.engines if e.enabled]
    return {"status": "ok" if usable else "unconfigured", "engines_enabled": usable}


@router.get("/engines")
def list_engines(request: Request) -> EnginesResponse:
    config = _config(request)
    engine_router = _router(request)
    infos = []
    for engine in config.engines:
        caps = capabilities_for(engine)
        status = engine_router.status(engine.id) or EngineStatus.DISABLED
        infos.append(
            EngineInfo(
                id=engine.id,
                kind=engine.kind,
                model=engine.model,
                capabilities=EngineCapabilitiesInfo(
                    html=caps.html.value,
                    glossary=caps.glossary,
                    max_input_tokens=caps.max_input_tokens,
                ),
                status=status.value,
                quota_resets_at=engine_router.quota_resets_at(engine.id),
            )
        )
    return EnginesResponse(engines=infos)


@router.post("/detect")
def detect(payload: DetectRequest) -> DetectResponse:
    results = [
        DetectionResult(language=d.language, confidence=d.confidence)
        for d in (detect_language(text) for text in payload.texts)
    ]
    return DetectResponse(results=results)


@router.post("/translate/text")
async def translate_text(
    payload: TranslateTextRequest, request: Request
) -> TranslateTextResponse:
    return await _router(request).translate_text(payload)


@router.post("/translate/html")
async def translate_html(
    payload: TranslateHtmlRequest, request: Request
) -> TranslateHtmlResponse:
    return await _router(request).translate_html(payload)
