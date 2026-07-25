"""The HTTP front end: FastAPI app, routes, and the admin dashboard.

``app`` assembles the application; ``routes`` holds one module per resource;
``deps`` gives routes the live config and router; ``dto`` holds HTTP-only
shapes. Nothing in ``core``, ``engines``, or ``text`` imports from here — the
translation core runs identically with no server at all.
"""

from .app import configure_logging, create_app

__all__ = ["configure_logging", "create_app"]
