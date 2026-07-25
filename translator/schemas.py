"""The translation contract: what callers send and what they get back.

Shared by both front ends — the HTTP API validates request bodies against
these models, and the embedded :class:`~translator.service.TranslatorService`
accepts and returns the same types. Shapes that only exist to serve HTTP
(engine listings, error envelopes) live in ``translator.server.dto`` instead.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from .text.languages import canonicalize

# Upper bounds on request payloads. Generous for real novel content while
# keeping a single request from consuming unbounded memory or engine quota.
MAX_TEXT_CHARS = 10_000
MAX_HTML_CHARS = 1_000_000
MAX_CONTEXT_CHARS = 5_000

TextItem = Annotated[str, StringConstraints(max_length=MAX_TEXT_CHARS)]
ContextStr = Annotated[str, StringConstraints(max_length=MAX_CONTEXT_CHARS)]
# BCP 47 tag: ISO 639-1 primary subtag + optional script/region subtag,
# canonicalized (zh-tw -> zh-Hant, pt-br -> pt-BR). Invalid tags 422.
LangCode = Annotated[str, AfterValidator(canonicalize)]


class TranslateTextRequest(BaseModel):
    texts: list[TextItem] = Field(min_length=1, max_length=500)
    source_lang: LangCode | None = Field(
        default=None,
        description="ISO 639-1 language code; autodetected when unset",
    )
    target_lang: LangCode = Field(
        default="en",
        description="ISO 639-1 language code",
    )
    glossary: dict[str, str] = {}
    context: ContextStr | None = None
    engine: str | None = None


class TranslateTextResponse(BaseModel):
    translations: list[str]
    detected_source_lang: str | None = None
    engine: str
    new_terms: dict[str, str] = {}


class HtmlContext(BaseModel):
    novel_title: ContextStr | None = None
    synopsis: ContextStr | None = None
    chapter_title: ContextStr | None = None
    previous_chapter_tail: ContextStr | None = None


class TranslateHtmlRequest(BaseModel):
    html: str = Field(min_length=1, max_length=MAX_HTML_CHARS)
    source_lang: LangCode | None = Field(
        default=None,
        description="ISO 639-1 language code; autodetected when unset",
    )
    target_lang: LangCode = Field(
        default="en",
        description="ISO 639-1 language code",
    )
    glossary: dict[str, str] = {}
    context: HtmlContext | None = None
    engine: str | None = None
    extract_terms: bool = True


class TranslateHtmlResponse(BaseModel):
    html: str
    detected_source_lang: str | None = None
    engine: str
    new_terms: dict[str, str] = {}
    warnings: list[str] = []
