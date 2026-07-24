"""lncrawl-translator: web-novel translation with switchable engines.

Public entry points (lazily imported so ``import translator`` stays light):

- ``TranslatorService`` — embedded sync service for host applications.
- ``detect_language`` / ``Detection`` — local language detection.
- ``create_app`` — FastAPI app factory (dashboard + HTTP API).
"""

from typing import Any

__version__ = "0.1.0"

__all__ = [
    "Detection",
    "TranslatorService",
    "__version__",
    "create_app",
    "detect_language",
]


def __getattr__(name: str) -> Any:
    if name == "TranslatorService":
        from .service import TranslatorService

        return TranslatorService
    if name == "detect_language":
        from .detect import detect_language

        return detect_language
    if name == "Detection":
        from .detect import Detection

        return Detection
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
