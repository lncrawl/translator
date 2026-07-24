"""Forced-terminology for engines without a native per-request dictionary.

Machine-translation engines that can't take a glossary get terms enforced by
substitution: each source term is replaced with a single private-use-area
placeholder codepoint before translation, then the placeholder is swapped for
the target term in the result. Single-codepoint placeholders are the least
likely thing for an engine to split, reorder, or translate — but this is
best-effort: an engine that drops unknown symbols will lose the term. Engines
with native forced-terminology (e.g. Bing's ``mstrans:dictionary``) should use
that instead.
"""

from __future__ import annotations

_PUA_START = 0xE000
_PUA_END = 0xF8FF  # end of the BMP Private Use Area


def protect(text: str, glossary: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Replace glossary source terms in ``text`` with placeholder codepoints.

    Returns the protected text and a placeholder -> target-term map to pass to
    :func:`reinject` after translation.
    """
    if not glossary or not text:
        return text, {}
    mapping: dict[str, str] = {}
    # Longest terms first so a term that contains a shorter one wins.
    for src, dst in sorted(glossary.items(), key=lambda kv: len(kv[0]), reverse=True):
        if not src or src not in text:
            continue
        codepoint = _PUA_START + len(mapping)
        if codepoint > _PUA_END:
            break  # placeholder space exhausted; leave remaining terms untouched
        placeholder = chr(codepoint)
        text = text.replace(src, placeholder)
        mapping[placeholder] = dst
    return text, mapping


def reinject(text: str, mapping: dict[str, str]) -> str:
    """Swap placeholders produced by :func:`protect` for their target terms."""
    for placeholder, dst in mapping.items():
        text = text.replace(placeholder, dst)
    return text
