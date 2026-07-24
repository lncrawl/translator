"""Opt-in tests against real configured engines.

Run with:

    LIVE_ENGINE_TEST=1 uv run pytest tests/test_live.py -s

Requires a config.yml (or $TRANSLATOR_CONFIG) with at least one engine whose
API key env var is set. Every enabled engine is exercised with one short-text
call and one small HTML call — this costs a trivial amount of quota.
"""

from __future__ import annotations

import os

import pytest

from translator.config import load_config
from translator.schemas import TranslateHtmlRequest, TranslateTextRequest
from translator.state import build_router

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_ENGINE_TEST") != "1",
    reason="live engine tests are opt-in: set LIVE_ENGINE_TEST=1",
)


async def test_every_enabled_engine_translates() -> None:
    config = load_config()
    enabled = [e for e in config.engines if e.enabled]
    if not enabled:
        pytest.skip("no enabled engines in config")
    router = build_router(config)
    failures: list[str] = []
    try:
        for engine in enabled:
            try:
                text = await router.translate_text(
                    TranslateTextRequest(
                        texts=["斗破苍穹"], source_lang="zh", engine=engine.id
                    )
                )
                assert text.translations[0].strip()
                print(f"\n[{engine.id}] title: {text.translations[0]!r}")

                html = await router.translate_html(
                    TranslateHtmlRequest(
                        html="<p>萧炎走了进来，看着面前的老者。</p>",
                        source_lang="zh",
                        glossary={"萧炎": "Xiao Yan"},
                        engine=engine.id,
                    )
                )
                assert html.html.strip()
                assert "<p>" in html.html
                print(f"[{engine.id}] html: {html.html!r}")
                if html.warnings:
                    print(f"[{engine.id}] warnings: {html.warnings}")
            except Exception as exc:  # noqa: BLE001 — collect per-engine results
                failures.append(f"{engine.id}: {exc}")
    finally:
        await router.close()
    assert not failures, "engines failed: " + "; ".join(failures)
