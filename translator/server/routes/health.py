"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter

from ... import __version__
from ...engines import is_available, resolve_all
from ..deps import ConfigDep
from ..dto import HealthResponse

router = APIRouter(tags=["service"])


@router.get("/health")
def health(config: ConfigDep) -> HealthResponse:
    """``unconfigured`` means the service is up but has no usable engine —
    every lane is disabled or missing its credentials."""
    usable = [r.id for r in resolve_all(config) if is_available(r)]
    return HealthResponse(
        status="ok" if usable else "unconfigured",
        version=__version__,
        engines_enabled=usable,
    )
