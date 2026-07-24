"""Embedded TranslatorService: sync facade, loop bridging, mounted app."""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from helpers import FakeEngine, make_config

from translator.router import Router
from translator.schemas import HtmlContext, TranslateTextRequest
from translator.service import AbortedError, TranslatorService


def make_service(*engines: FakeEngine) -> TranslatorService:
    config = make_config(*[e.id for e in engines])
    service = TranslatorService(config=config, config_path=None)
    service.store.router = Router(list(engines), config)
    return service


def test_translate_text_from_sync_caller() -> None:
    service = make_service(FakeEngine("e1"))
    try:
        response = service.translate_text(
            {"texts": ["hello"], "target_lang": "en", "source_lang": "en"}
        )
        assert response.translations == ["e1:hello"]
        assert response.engine == "e1"
    finally:
        service.close()


def test_translate_text_from_worker_threads() -> None:
    service = make_service(FakeEngine("e1"))
    results: list[str] = []

    def work() -> None:
        request = TranslateTextRequest(texts=["hi"], target_lang="en", source_lang="en")
        results.append(service.translate_text(request).translations[0])

    try:
        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == ["e1:hi"] * 4
    finally:
        service.close()


def test_translate_html_and_detect() -> None:
    service = make_service(FakeEngine("e1"))
    try:
        response = service.translate_html(
            {
                "html": "<p>hello world</p>",
                "target_lang": "en",
                "source_lang": "en",
                "context": HtmlContext(novel_title="t").model_dump(),
            }
        )
        assert "[e1]" in response.html
        detections = service.detect(["안녕하세요 여러분, 만나서 반갑습니다"])
        assert detections[0].language == "ko"
    finally:
        service.close()


def test_abort_signal_cancels_call() -> None:
    class SlowEngine(FakeEngine):
        async def translate_segments(self, segments, **kwargs):  # type: ignore[no-untyped-def]
            await asyncio.sleep(30)
            return segments

    service = make_service(SlowEngine("slow"))
    try:
        signal = threading.Event()
        signal.set()
        with pytest.raises(AbortedError):
            service.translate_text(
                {"texts": ["x"], "target_lang": "en", "source_lang": "en"},
                signal=signal,
            )
    finally:
        service.close()


def test_mounted_app_shares_store_and_hops_loops() -> None:
    service = make_service(FakeEngine("e1"))
    try:
        app = service.create_app()
        client = TestClient(app)
        # Translate endpoint hops onto the service loop via ConfigStore.run.
        response = client.post(
            "/translate/text",
            json={"texts": ["hey"], "target_lang": "en", "source_lang": "en"},
        )
        assert response.status_code == 200
        assert response.json()["translations"] == ["e1:hey"]
        # The dashboard shell and the health endpoint are served too.
        assert client.get("/health").status_code == 200
        # Admin mutations apply on the service loop and are visible to it.
        response = client.put(
            "/routing", json={"chapter": ["e1"], "short_text": ["e1"]}
        )
        assert response.status_code == 200
        assert service.config.routing.chapter == ["e1"]
    finally:
        service.close()


def test_service_construction_from_worker_thread() -> None:
    # Engines must not bind asyncio primitives at construction: the embedded
    # service is built lazily on whatever host thread first needs it, and
    # Python 3.9 binds primitives to a loop at construction time.
    from pathlib import Path

    from translator.config import load_config

    errors: list[Exception] = []

    def work() -> None:
        try:
            service = TranslatorService(config=load_config(Path("/nonexistent.yml")))
            service.detect(["hello world"])
            service.close()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(30)
    assert not errors, errors
