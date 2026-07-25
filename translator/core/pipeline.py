"""The translation workflow: what happens around an engine call.

Source-language resolution, glossary narrowing, HTML chunking, per-chunk
context threading, and response assembly. Each entry point builds a coroutine
factory and hands it to the router, which decides *which* engine runs it and
what to do when one fails.
"""

from __future__ import annotations

from ..engines import Engine, EngineError, ErrorKind, HtmlResult, HtmlSupport
from ..schemas import (
    HtmlContext,
    TranslateHtmlRequest,
    TranslateHtmlResponse,
    TranslateTextRequest,
    TranslateTextResponse,
)
from ..text.detect import detect_language
from ..text.glossary import filter_glossary
from ..text.html import chunk_html, extract_segments, strip_text
from .router import Router

# Assumed context budget for an engine that declares none.
DEFAULT_CONTEXT_TOKENS = 32_000
# Fraction of an engine's context budget a single source chunk may occupy
# (the rest is for the prompt scaffold and the translated output).
SOURCE_BUDGET_FRACTION = 0.3
# How much of the preceding chunk's translation to carry forward as context.
CHUNK_TAIL_CHARS = 500
# Language samples: enough text to detect from without scanning a whole chapter.
DETECT_SAMPLE_TEXTS = 20


def resolve_source_lang(
    requested: str | None, sample: str
) -> tuple[str | None, str | None]:
    """Returns (lang for engines, detected lang for the response)."""
    if requested:
        return requested, None
    detection = detect_language(sample)
    if detection.language == "und":
        return None, None
    return detection.language, detection.language


async def translate_text(
    router: Router, request: TranslateTextRequest
) -> TranslateTextResponse:
    source_lang, detected = resolve_source_lang(
        request.source_lang, "\n".join(request.texts[:DETECT_SAMPLE_TEXTS])
    )
    glossary = filter_glossary(request.glossary, request.texts)

    async def fn(engine: Engine) -> list[str]:
        return await engine.translate_segments(
            request.texts,
            source_lang=source_lang,
            target_lang=request.target_lang,
            glossary=glossary,
            context=request.context,
        )

    translations, engine_id = await router.run(
        "short_text",
        request.engine,
        fn,
        source_lang=source_lang,
        target_lang=request.target_lang,
    )
    return TranslateTextResponse(
        translations=translations,
        detected_source_lang=detected,
        engine=engine_id,
    )


async def translate_html(
    router: Router, request: TranslateHtmlRequest
) -> TranslateHtmlResponse:
    text = strip_text(request.html)
    source_lang, detected = resolve_source_lang(request.source_lang, text)
    glossary = filter_glossary(request.glossary, [text])

    async def fn(engine: Engine) -> HtmlResult:
        if engine.capabilities.html is HtmlSupport.NONE:
            return await translate_via_segments(
                engine,
                request.html,
                source_lang=source_lang,
                target_lang=request.target_lang,
                glossary=glossary,
            )
        return await translate_in_chunks(
            engine,
            request,
            source_lang=source_lang,
            glossary=glossary,
        )

    result, engine_id = await router.run(
        "chapter",
        request.engine,
        fn,
        source_lang=source_lang,
        target_lang=request.target_lang,
    )
    return TranslateHtmlResponse(
        html=result.html,
        detected_source_lang=detected,
        engine=engine_id,
        new_terms={
            k: v for k, v in result.new_terms.items() if k not in request.glossary
        },
        warnings=result.warnings,
    )


def _chunk_budget(engine: Engine) -> int:
    budget = engine.capabilities.max_input_tokens or DEFAULT_CONTEXT_TOKENS
    return engine.config.chunk_tokens or max(1000, int(budget * SOURCE_BUDGET_FRACTION))


async def translate_in_chunks(
    engine: Engine,
    request: TranslateHtmlRequest,
    *,
    source_lang: str | None,
    glossary: dict[str, str],
) -> HtmlResult:
    """Split the chapter to fit the engine's context and translate the pieces
    in order, carrying the glossary and the tail of each translation forward so
    later chunks stay consistent with earlier ones."""
    chunks = chunk_html(request.html, _chunk_budget(engine))
    warnings: list[str] = []
    if len(chunks) > 1:
        warnings.append(f"chapter split into {len(chunks)} chunks")
    if glossary and not engine.capabilities.glossary:
        warnings.append("glossary not applied: engine lacks glossary support")

    source = request.context
    parts: list[str] = []
    new_terms: dict[str, str] = {}
    running_glossary = dict(glossary)
    previous_tail = source.previous_chapter_tail if source else None
    for chunk in chunks:
        result = await engine.translate_html(
            chunk,
            source_lang=source_lang,
            target_lang=request.target_lang,
            glossary=running_glossary,
            context=HtmlContext(
                novel_title=source.novel_title if source else None,
                synopsis=source.synopsis if source else None,
                chapter_title=source.chapter_title if source else None,
                previous_chapter_tail=previous_tail,
            ),
            extract_terms=request.extract_terms,
        )
        parts.append(result.html)
        warnings.extend(result.warnings)
        new_terms.update(result.new_terms)
        # Later chunks see terms coined earlier and continue seamlessly.
        running_glossary.update(result.new_terms)
        previous_tail = strip_text(result.html)[-CHUNK_TAIL_CHARS:]
    return HtmlResult(html="".join(parts), new_terms=new_terms, warnings=warnings)


async def translate_via_segments(
    engine: Engine,
    html: str,
    *,
    source_lang: str | None,
    target_lang: str,
    glossary: dict[str, str],
    context: str | None = None,
) -> HtmlResult:
    """Fallback for engines that cannot handle markup themselves: extract the
    translatable text nodes, translate them as segments, reinject in place."""
    soup, nodes = extract_segments(html)
    if not nodes:
        return HtmlResult(html=html)
    translated = await engine.translate_segments(
        [str(n) for n in nodes],
        source_lang=source_lang,
        target_lang=target_lang,
        glossary=glossary,
        context=context,
    )
    if len(translated) != len(nodes):
        raise EngineError(
            f"{engine.id}: returned {len(translated)} segments for {len(nodes)}"
            " text nodes",
            ErrorKind.TRANSIENT,
        )
    for node, text in zip(nodes, translated):
        node.replace_with(text)
    return HtmlResult(
        html=str(soup),
        warnings=["segment-level translation: engine lacks HTML support"],
    )
