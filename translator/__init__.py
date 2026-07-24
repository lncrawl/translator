"""lncrawl-translator: web-novel translation with switchable engines.

Public entry points (lazily imported so ``import translator`` stays light):

- ``TranslatorService`` — embedded sync service for host applications.
- ``detect_language`` / ``detect_code`` / ``Detection`` — local language detection.
- ``create_app`` — FastAPI app factory (dashboard + HTTP API).
- ``TranslatorError`` / ``ApiError`` / ``AbortedError`` / ``InvalidRequestError`` — the
  exception taxonomy an embedding host maps against (no pydantic import required).
- ``TranslateTextResponse`` / ``TranslateHtmlResponse`` — response models (for typing).
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_version
from typing import Any

try:
    __version__ = get_version("lncrawl-translator")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"

__all__ = [
    "AbortedError",
    "ApiError",
    "Detection",
    "InvalidRequestError",
    "TranslateHtmlResponse",
    "TranslateTextResponse",
    "TranslatorError",
    "TranslatorService",
    "__version__",
    "create_app",
    "detect_code",
    "detect_language",
]


def __getattr__(name: str) -> Any:
    if name == "TranslatorService":
        from .service import TranslatorService

        return TranslatorService
    if name == "detect_language":
        from .detect import detect_language

        return detect_language
    if name == "detect_code":
        from .detect import detect_code

        return detect_code
    if name == "Detection":
        from .detect import Detection

        return Detection
    if name == "create_app":
        from .app import create_app

        return create_app
    if name in ("TranslatorError", "ApiError", "AbortedError", "InvalidRequestError"):
        from . import errors

        return getattr(errors, name)
    if name in ("TranslateTextResponse", "TranslateHtmlResponse"):
        from . import schemas

        return getattr(schemas, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
