"""Engine protocol: what every translation backend must provide."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from .._compat import StrEnum
from ..config import ResolvedEngine
from ..schemas import HtmlContext


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

    # Credentials a provider of this kind needs; empty means keyless.
    CREDENTIALS: list[CredentialField] = []

    def __init__(self, config: ResolvedEngine) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @property
    @abc.abstractmethod
    def capabilities(self) -> EngineCapabilities: ...

    def supports(self, source_lang: str | None, target_lang: str) -> bool:
        """Whether this engine can handle the pair, checked before dispatch so
        the router can skip it and reject unsupported pairs early. Delegates to
        the shared coverage logic keyed by kind + config allowlists."""
        from ..languages import supports_pair

        return supports_pair(self.config, source_lang, target_lang)

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
