"""The translation core: what to translate, on which engine, and what to do
when an engine fails.

- :mod:`~translator.core.limits` — live provider/engine health and throughput.
- :mod:`~translator.core.router` — lane selection, retries, and fallback.
- :mod:`~translator.core.pipeline` — the workflow around an engine call.
- :mod:`~translator.core.store` — the live config + router, swapped atomically.

Everything here is transport-agnostic: the HTTP layer and the embedded
``TranslatorService`` are two front ends over the same core.
"""

from .pipeline import translate_html, translate_text
from .router import Router, TaskKind, build_router
from .store import ConfigStore

__all__ = [
    "ConfigStore",
    "Router",
    "TaskKind",
    "build_router",
    "translate_html",
    "translate_text",
]
