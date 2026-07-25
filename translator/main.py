"""Standalone server entry point: ``uvicorn translator.main:app``.

Importing this module loads the config and builds the app; for a
side-effect-free factory use ``translator.create_app``.
"""

from .server import configure_logging, create_app

configure_logging()
app = create_app()
