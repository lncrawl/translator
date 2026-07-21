"""HTTP route handlers."""

from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from .config import AppConfig
from .detect import detect_language
from .engines import capabilities_for
from .errors import ApiError
from .schemas import (
    DetectionResult,
    DetectRequest,
    DetectResponse,
    EngineCapabilitiesInfo,
    EngineInfo,
    EnginesResponse,
    TranslateHtmlRequest,
    TranslateTextRequest,
)

AUTH_TOKEN_ENV = "AUTH_TOKEN"


def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token auth, active only when $AUTH_TOKEN is set."""
    token = os.environ.get(AUTH_TOKEN_ENV)
    if not token:
        return
    expected = f"Bearer {token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise ApiError(401, "unauthorized", "missing or invalid bearer token")


def _config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.config
    return config


health_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_auth)])


@health_router.get("/health")
def health(request: Request) -> dict[str, object]:
    config = _config(request)
    usable = [e.id for e in config.engines if e.enabled]
    return {"status": "ok" if usable else "unconfigured", "engines_enabled": usable}


@router.get("/engines")
def list_engines(request: Request) -> EnginesResponse:
    config = _config(request)
    infos = []
    for engine in config.engines:
        caps = capabilities_for(engine)
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
                status="ok" if engine.enabled else "disabled",
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
def translate_text(payload: TranslateTextRequest, request: Request) -> None:
    raise ApiError(501, "not_implemented", "text translation lands in a later part")


@router.post("/translate/html")
def translate_html(payload: TranslateHtmlRequest, request: Request) -> None:
    raise ApiError(501, "not_implemented", "HTML translation lands in a later part")
