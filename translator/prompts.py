"""Prompt construction and response parsing for LLM engines."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from .languages import display_name as lang_name
from .schemas import HtmlContext

_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
_TRANSLATION_BLOCK = re.compile(r"<TRANSLATION>\s*(.*?)\s*</TRANSLATION>", re.DOTALL)
_NEW_TERMS_BLOCK = re.compile(r"<NEW_TERMS>\s*(.*?)\s*</NEW_TERMS>", re.DOTALL)
# Reasoning models may prepend chain-of-thought despite instructions.
_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_reasoning(raw: str) -> str:
    return _THINK_BLOCK.sub("", raw)


def filter_glossary(glossary: dict[str, str], sources: Iterable[str]) -> dict[str, str]:
    """Keep only terms that actually occur in the source text, to save tokens."""
    if not glossary:
        return {}
    haystack = "\n".join(sources)
    return {k: v for k, v in glossary.items() if k in haystack}


def _strip_fences(raw: str) -> str:
    return _FENCE.sub("", raw.strip())


def _glossary_lines(glossary: dict[str, str]) -> str:
    if not glossary:
        return ""
    table = "\n".join(f"- {src} => {dst}" for src, dst in glossary.items())
    return (
        "\nGlossary — use these exact translations for these terms,"
        f" every time they occur:\n{table}\n"
    )


def build_text_messages(
    texts: list[str],
    *,
    source_lang: str | None,
    target_lang: str,
    glossary: dict[str, str],
    context: str | None,
) -> list[dict[str, str]]:
    system = (
        f"You are a professional translator of {lang_name(source_lang)} web novels"
        f" into {lang_name(target_lang)}. You translate titles, names, tags, and"
        " synopses so they read naturally while staying faithful to the source."
        " Proper nouns are romanized or translated consistently."
    )
    parts = [
        f"Translate each string in the JSON array below from"
        f" {lang_name(source_lang)} to {lang_name(target_lang)}."
    ]
    if context:
        parts.append(f"Context: {context}")
    if glossary:
        parts.append(_glossary_lines(glossary).strip())
    parts.append(
        "Respond with ONLY a JSON array of the translated strings, in the same"
        " order, with the same number of elements. No commentary, no code fence."
    )
    parts.append(json.dumps(texts, ensure_ascii=False))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def parse_text_response(raw: str, expected: int) -> list[str]:
    """Parse the JSON array reply. Raises ValueError on shape mismatch."""
    cleaned = _strip_fences(strip_reasoning(raw))
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("no JSON array in engine response")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, list) or len(data) != expected:
        raise ValueError(
            f"expected {expected} translations, got"
            f" {len(data) if isinstance(data, list) else type(data).__name__}"
        )
    return [str(item) for item in data]


def build_html_messages(
    html: str,
    *,
    source_lang: str | None,
    target_lang: str,
    glossary: dict[str, str],
    context: HtmlContext | None,
    extract_terms: bool,
) -> list[dict[str, str]]:
    system = (
        f"You are a professional literary translator of {lang_name(source_lang)}"
        f" web novels into {lang_name(target_lang)}. You produce fluent, natural"
        " prose that preserves the author's tone, register, and paragraph"
        " structure.\n\nRules:\n"
        "1. Preserve ALL HTML tags and attributes exactly as they appear —"
        " translate only human-readable text content.\n"
        "2. Never translate content inside <code>, <pre>, or any element with"
        ' translate="no".\n'
        "3. Use the glossary translations verbatim wherever those terms occur.\n"
        "4. Do not add, remove, merge, or reorder paragraphs.\n"
        "5. Output the translated HTML between <TRANSLATION> and </TRANSLATION>"
        " markers."
    )
    if extract_terms:
        system += (
            "\n6. After the translation, output <NEW_TERMS>{...}</NEW_TERMS>"
            " containing a JSON object of proper nouns you encountered that are"
            " NOT in the glossary (characters, places, organizations, techniques,"
            " titles). Each key MUST be the term exactly as written in the"
            " untranslated source text; each value is the translation you chose"
            ' — for example {"萧炎": "Xiao Yan", "斗气大陆": "Dou Qi Continent"}.'
            " Never use a translated term as a key. Use {} if there are none."
        )

    parts: list[str] = []
    if context:
        ctx_lines = []
        if context.novel_title:
            ctx_lines.append(f"Novel: {context.novel_title}")
        if context.chapter_title:
            ctx_lines.append(f"Chapter: {context.chapter_title}")
        if context.synopsis:
            ctx_lines.append(f"Synopsis: {context.synopsis}")
        if ctx_lines:
            parts.append("\n".join(ctx_lines))
        if context.previous_chapter_tail:
            parts.append(
                "End of the previous translated chapter, for continuity of tone"
                f" and tense:\n…{context.previous_chapter_tail}"
            )
    if glossary:
        parts.append(_glossary_lines(glossary).strip())
    parts.append(f"Translate this chapter to {lang_name(target_lang)}:\n\n{html}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def parse_html_response(raw: str) -> tuple[str, dict[str, str]]:
    """Extract (translated_html, new_terms) from the engine reply.

    Lenient: missing markers fall back to the whole reply; unparseable
    NEW_TERMS yields {} — term extraction must never fail a translation.
    """
    raw = strip_reasoning(raw)
    new_terms: dict[str, str] = {}
    terms_match = _NEW_TERMS_BLOCK.search(raw)
    if terms_match:
        block = terms_match.group(1)
        start, end = block.find("{"), block.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(block[start : end + 1])
                if isinstance(data, dict):
                    new_terms = {str(k): str(v) for k, v in data.items()}
            except json.JSONDecodeError:
                pass

    translation_match = _TRANSLATION_BLOCK.search(raw)
    if translation_match:
        html = translation_match.group(1)
    else:
        html = _NEW_TERMS_BLOCK.sub("", raw)
        html = _strip_fences(html)
        html = html.replace("<TRANSLATION>", "").replace("</TRANSLATION>", "")
        html = html.strip()
    return html, new_terms
