"""HTTP routes, one module per resource.

Aggregated here into a single router so the app factory mounts one thing and
route paths stay independent of how the modules are split.
"""

from fastapi import APIRouter

from . import config, dashboard, engines, health, providers, translate
from .dashboard import mount_static

router = APIRouter()
for _module in (dashboard, health, translate, engines, providers, config):
    router.include_router(_module.router)

__all__ = ["mount_static", "router"]
