"""End-to-end checks against realistic chapter fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from helpers import FakeEngine, make_config

from translator.app import create_app
from translator.detect import detect_language
from translator.engines.base import HtmlSupport
from translator.html_tools import chunk_html, extract_segments, tag_names
from translator.router import Router

FIXTURES = Path(__file__).parent / "fixtures"
LANGS = ["zh", "ja", "ko"]


def fixture(lang: str) -> str:
    return (FIXTURES / f"{lang}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("lang", LANGS)
def test_fixture_language_detected(lang: str) -> None:
    detection = detect_language(fixture(lang))
    assert detection.language == lang
    assert detection.confidence > 0.7


@pytest.mark.parametrize("lang", LANGS)
def test_fixture_chunking_reassembles_structurally(lang: str) -> None:
    """Chunk boundaries may normalize attribute order (parser round-trip),
    so compare parsed structure rather than bytes."""
    html = fixture(lang)
    chunks = chunk_html(html, max_tokens=150)
    assert len(chunks) > 1
    joined = "".join(chunks)
    assert BeautifulSoup(joined, "html.parser") == BeautifulSoup(html, "html.parser")


@pytest.mark.parametrize("lang", LANGS)
def test_fixture_segments_extracted(lang: str) -> None:
    _, nodes = extract_segments(fixture(lang))
    # Every fixture has a heading and at least six paragraphs of text.
    assert len(nodes) >= 7
    # The empty-alt image contributes no segment.
    assert all(str(n).strip() for n in nodes)


@pytest.mark.parametrize("lang", LANGS)
def test_full_pipeline_preserves_tag_structure(lang: str) -> None:
    """A whole chapter through the API using the segment pipeline: the
    translated document must keep the exact tag structure of the source."""
    html = fixture(lang)
    engine = FakeEngine("fake", html_support=HtmlSupport.NONE)
    config = make_config("fake")
    router = Router([engine], config, transient_retries=0, backoff_base_seconds=0)
    client = TestClient(create_app(config, router))

    resp = client.post("/translate/html", json={"html": html})
    assert resp.status_code == 200
    body = resp.json()
    assert tag_names(body["html"]) == tag_names(html)
    assert body["detected_source_lang"] == lang
    # Image src attributes survive untouched.
    assert 'src="images/stone-tablet.jpg"' in body["html"] or lang != "zh"
