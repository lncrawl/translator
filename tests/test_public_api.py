"""The top-level ``translator`` namespace an embedding host depends on."""

from __future__ import annotations

import translator


def test_error_taxonomy_shares_a_common_base() -> None:
    assert issubclass(translator.ApiError, translator.TranslatorError)
    assert issubclass(translator.AbortedError, translator.TranslatorError)
    assert issubclass(translator.InvalidRequestError, translator.TranslatorError)


def test_aborted_error_is_importable_from_service_namespace() -> None:
    # Backward compat: existing hosts import it from translator.service.
    from translator.service import AbortedError as ServiceAbortedError

    assert ServiceAbortedError is translator.AbortedError


def test_api_error_is_importable_from_errors_namespace() -> None:
    from translator.errors import ApiError as ErrorsApiError

    assert ErrorsApiError is translator.ApiError


def test_public_symbols_are_exposed() -> None:
    for name in (
        "TranslatorService",
        "TranslatorError",
        "ApiError",
        "AbortedError",
        "InvalidRequestError",
        "detect_code",
        "detect_language",
        "Detection",
        "create_app",
        "TranslateTextResponse",
        "TranslateHtmlResponse",
    ):
        assert hasattr(translator, name), name
        assert name in translator.__all__, name


def test_unknown_attribute_still_raises() -> None:
    import pytest

    with pytest.raises(AttributeError):
        _ = translator.does_not_exist
