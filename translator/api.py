"""HTTP route handlers."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from . import __version__
from .config import AppConfig, EngineKind
from .detect import detect_language
from .engines import (
    CredentialField,
    EngineStatus,
    capabilities_for,
    credential_fields,
    is_available,
)
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

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


def _config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.store.config
    return config


def _router(request: Request) -> Router:
    engine_router: Router = request.app.state.store.router
    return engine_router


health_router = APIRouter()
router = APIRouter()


@health_router.get("/", include_in_schema=False)
def root() -> FileResponse:
    """Dashboard app shell; assets are served from /static."""
    return FileResponse(INDEX_HTML, media_type="text/html")


@health_router.get("/health", tags=["service"])
def health(request: Request) -> dict[str, object]:
    config = _config(request)
    usable = [r.id for r in config.resolved_engines() if is_available(r)]
    return {
        "status": "ok" if usable else "unconfigured",
        "version": __version__,
        "engines_enabled": usable,
    }


@router.get("/config", tags=["config"])
def get_config(request: Request) -> AppConfig:
    """The live config, including provider API keys."""
    return _config(request)


@router.get("/credential-schema", tags=["config"])
def credential_schema() -> dict[str, list[CredentialField]]:
    """Per-kind credential fields, so the dashboard renders the right inputs."""
    return {kind: credential_fields(kind) for kind in get_args(EngineKind)}


@router.get("/engines", tags=["engines"])
def list_engines(request: Request) -> EnginesResponse:
    config = _config(request)
    engine_router = _router(request)
    infos = []
    for resolved in config.resolved_engines():
        caps = capabilities_for(resolved)
        status = engine_router.status(resolved.id) or EngineStatus.DISABLED
        infos.append(
            EngineInfo(
                id=resolved.id,
                provider=resolved.provider_id,
                kind=resolved.kind,
                model=resolved.model,
                enabled=is_available(resolved),
                capabilities=EngineCapabilitiesInfo(
                    html=caps.html.value,
                    glossary=caps.glossary,
                    max_input_tokens=caps.max_input_tokens,
                ),
                status=status.value,
                retry_at=engine_router.retry_at(resolved.id),
            )
        )
    return EnginesResponse(engines=infos)


@router.post("/detect", tags=["translation"])
def detect(payload: DetectRequest) -> DetectResponse:
    results = [
        DetectionResult(language=d.language, confidence=d.confidence)
        for d in (detect_language(text) for text in payload.texts)
    ]
    return DetectResponse(results=results)


@router.post("/translate/text", tags=["translation"])
async def translate_text(
    payload: TranslateTextRequest, request: Request
) -> TranslateTextResponse:
    return await _router(request).translate_text(payload)


@router.post("/translate/html", tags=["translation"])
async def translate_html(
    payload: TranslateHtmlRequest, request: Request
) -> TranslateHtmlResponse:
    return await _router(request).translate_html(payload)
