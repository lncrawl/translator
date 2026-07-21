"""HTML utilities: token estimation, chunking, segment pipeline, validation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

if TYPE_CHECKING:
    from .engines.base import Engine, HtmlResult

# Tags whose text content must never be translated.
SKIP_TAGS = {"script", "style", "code", "pre"}

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿぀-ヿㇰ-ㇿｦ-ﾟ가-힯]")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: CJK ≈ 1 token/char, other text ≈ 1 token/4 chars."""
    cjk = count_cjk(text)
    return cjk + (len(text) - cjk) // 4 + 1


def count_cjk(text: str) -> int:
    return len(_CJK.findall(text))


def strip_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(" ")


def tag_names(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [t.name for t in soup.find_all()]


def chunk_html(html: str, max_tokens: int) -> list[str]:
    """Split HTML on top-level element boundaries into ≤ max_tokens pieces.

    A single oversized element becomes its own chunk rather than being split
    mid-markup.
    """
    if estimate_tokens(html) <= max_tokens:
        return [html]
    soup = BeautifulSoup(html, "html.parser")
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for child in soup.contents:
        piece = str(child)
        tokens = estimate_tokens(piece)
        if current and current_tokens + tokens > max_tokens:
            chunks.append("".join(current))
            current, current_tokens = [], 0
        current.append(piece)
        current_tokens += tokens
    if current:
        chunks.append("".join(current))
    return chunks


def _is_translatable(node: NavigableString) -> bool:
    for parent in node.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in SKIP_TAGS or parent.get("translate") == "no":
            return False
    return True


def extract_segments(html: str) -> tuple[BeautifulSoup, list[NavigableString]]:
    """Parse HTML and return the tree plus its translatable text nodes."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = [
        node
        for node in soup.find_all(string=True)
        if node.strip() and _is_translatable(node)
    ]
    return soup, nodes


async def translate_html_via_segments(
    engine: Engine,
    html: str,
    *,
    source_lang: str | None,
    target_lang: str,
    glossary: dict[str, str],
    context: str | None = None,
) -> HtmlResult:
    """Fallback pipeline for engines that cannot handle markup themselves:
    extract text nodes, translate them as segments, reinject in place."""
    from .engines.base import HtmlResult

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
    for node, text in zip(nodes, translated, strict=True):
        node.replace_with(text)
    return HtmlResult(
        html=str(soup),
        warnings=["segment-level translation: engine lacks HTML support"],
    )


def repair_untagged_output(source_html: str, output: str) -> str | None:
    """If the engine returned plain text for tagged input, re-wrap it in
    paragraphs. Returns None when no repair applies."""
    if not tag_names(source_html) or tag_names(output):
        return None
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", output) if p.strip()]
    if not paragraphs:
        return None
    return "".join(f"<p>{p}</p>" for p in paragraphs)
