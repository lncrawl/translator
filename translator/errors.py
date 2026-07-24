"""Structured errors shared across the service.

``TranslatorError`` is the common base for everything a caller can catch, so an
embedding host maps semantic exceptions without importing pydantic or reaching
into internal modules. ``ApiError`` additionally carries HTTP-shaped fields for
the standalone server's exception handler.
"""

from __future__ import annotations

from typing import Any


class TranslatorError(Exception):
    """Base for every error the translator surfaces to callers."""


class ApiError(TranslatorError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after_seconds = retry_after_seconds


class InvalidRequestError(TranslatorError):
    """A request failed validation before reaching an engine."""

    def __init__(self, message: str, *, errors: list[Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or []


class AbortedError(TranslatorError):
    """The call was cancelled via its abort signal or timed out."""
