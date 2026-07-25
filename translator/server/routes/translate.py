"""Translation and language detection."""

from __future__ import annotations

from fastapi import APIRouter

from ...core import pipeline
from ...schemas import (
    TranslateHtmlRequest,
    TranslateHtmlResponse,
    TranslateTextRequest,
    TranslateTextResponse,
)
from ...text.detect import detect_language
from ..deps import StoreDep
from ..dto import DetectionResult, DetectRequest, DetectResponse

router = APIRouter(tags=["translation"])


@router.post("/detect")
def detect(payload: DetectRequest) -> DetectResponse:
    results = [
        DetectionResult(language=d.language, confidence=d.confidence)
        for d in (detect_language(text) for text in payload.texts)
    ]
    return DetectResponse(results=results)


@router.post("/translate/text")
async def translate_text(
    payload: TranslateTextRequest, store: StoreDep
) -> TranslateTextResponse:
    return await store.run(pipeline.translate_text(store.router, payload))


@router.post("/translate/html")
async def translate_html(
    payload: TranslateHtmlRequest, store: StoreDep
) -> TranslateHtmlResponse:
    return await store.run(pipeline.translate_html(store.router, payload))
