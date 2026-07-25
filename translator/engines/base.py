"""Engine protocol: what every translation backend must provide.

A backend declares itself entirely through class attributes and classmethods —
its ``KIND``, the credentials it needs, the capabilities it offers, and the
languages it covers. All of that is answerable *without instantiating* the
engine, which is what lets the registry describe disabled or unconfigured
engines and lets the router gate language pairs before dispatch.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import ClassVar

from .._compat import StrEnum
from ..config import EngineKind, ResolvedEngine
from ..schemas import HtmlContext
from ..text.languages import allowed as lang_allowed


class HtmlSupport(StrEnum):
    NATIVE = "native"  # provider preserves markup itself (e.g. DeepL)
    PROMPT = "prompt"  # LLM: preserve markup via instructions + validation
    NONE = "none"  # service must strip/reinject markup around the engine


class ErrorKind(StrEnum):
    TRANSIENT = "transient"  # retry same engine with backoff
    QUOTA = "quota"  # mark engine exhausted, try next lane
    FATAL = "fatal"  # skip to next lane immediately


class EngineStatus(StrEnum):
    OK = "ok"
    THROTTLED = "throttled"
    QUOTA_EXHAUSTED = "quota_exhausted"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(frozen=True)
class EngineCapabilities:
    html: HtmlSupport
    glossary: bool
    max_input_tokens: int | None = None
    # Base ISO 639-1 languages the engine covers; None means unrestricted.
    source_langs: list[str] | None = None
    target_langs: list[str] | None = None


@dataclass(frozen=True)
class CredentialField:
    """One credential a provider of this engine kind needs.

    ``key`` is where the value lives on the resolved engine: ``"api_key"`` for
    the conventional single secret, otherwise a key in the provider ``options``
    bag (e.g. ``"secret_key"``). Drives the availability gate and the
    dashboard's dynamic credential form.
    """

    key: str
    label: str
    secret: bool = True
    required: bool = True
    description: str | None = None


@dataclass
class HtmlResult:
    html: str
    new_terms: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class EngineError(Exception):
    def __init__(
        self,
        message: str,
        kind: ErrorKind,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds


class Engine(abc.ABC):
    """A translation backend. Instances are long-lived and concurrency-safe."""

    # The config ``kind`` this class implements; the registry keys on it.
    KIND: ClassVar[EngineKind]
    # Credentials a provider of this kind needs; empty means keyless.
    CREDENTIALS: ClassVar[list[CredentialField]] = []
    # How the backend handles markup, and whether glossary terms are enforced
    # (natively by the provider, or by the substitution this package does).
    HTML: ClassVar[HtmlSupport]
    GLOSSARY: ClassVar[bool] = True

    def __init__(self, config: ResolvedEngine) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    # -- description (answerable without an instance) --------------------------

    @classmethod
    def describe(cls, config: ResolvedEngine) -> EngineCapabilities:
        """Capabilities of this kind under ``config``. The single source of
        truth: the instance property below forwards to it, so a listed engine
        and a running one can never report different capabilities."""
        source_langs, target_langs = cls.coverage(config)
        return EngineCapabilities(
            html=cls.HTML,
            glossary=cls.GLOSSARY,
            max_input_tokens=cls.max_input_tokens(config),
            source_langs=source_langs,
            target_langs=target_langs,
        )

    @classmethod
    def max_input_tokens(cls, config: ResolvedEngine) -> int | None:
        """Context budget for one request; ``None`` means unconstrained.
        Kinds with a hard service limit clamp the configured value."""
        return config.max_input_tokens

    @classmethod
    def coverage(
        cls, config: ResolvedEngine
    ) -> tuple[list[str] | None, list[str] | None]:
        """(source, target) base languages covered, ``None`` meaning
        unrestricted. LLM and broad NMT kinds accept any pair; a kind with a
        finite catalog overrides this to declare it."""
        return config.source_langs, config.target_langs

    @classmethod
    def supports_pair(
        cls, config: ResolvedEngine, source_lang: str | None, target_lang: str
    ) -> bool:
        """Whether this kind can handle the pair under ``config``. Checked
        before dispatch so the router can skip the engine and reject
        unsupported pairs early. Config allowlists apply to every kind; a kind
        with a finite catalog narrows further by overriding."""
        return lang_allowed(source_lang, config.source_langs) and lang_allowed(
            target_lang, config.target_langs
        )

    @property
    def capabilities(self) -> EngineCapabilities:
        return type(self).describe(self.config)

    def supports(self, source_lang: str | None, target_lang: str) -> bool:
        return type(self).supports_pair(self.config, source_lang, target_lang)

    # -- translation -----------------------------------------------------------

    @abc.abstractmethod
    async def translate_segments(
        self,
        segments: list[str],
        *,
        source_lang: str | None,
        target_lang: str,
        glossary: dict[str, str],
        context: str | None = None,
    ) -> list[str]:
        """Translate plain-text segments, preserving order and count."""

    async def translate_html(
        self,
        html: str,
        *,
        source_lang: str | None,
        target_lang: str,
        glossary: dict[str, str],
        context: HtmlContext | None = None,
        extract_terms: bool = True,
    ) -> HtmlResult:
        """Translate an HTML fragment. Only for engines with html != NONE."""
        raise NotImplementedError(f"{self.id} does not translate HTML directly")

    async def close(self) -> None:  # noqa: B027 — optional override, no-op default
        """Release network resources; called on service shutdown."""
