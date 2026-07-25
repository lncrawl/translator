"""The admin dashboard: an SPA shell plus its static assets."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
INDEX_HTML = STATIC_DIR / "index.html"

router = APIRouter()


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Dashboard app shell; assets are served from /static."""
    return FileResponse(INDEX_HTML, media_type="text/html")


def mount_static(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
