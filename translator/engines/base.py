"""Engine protocol: what every translation backend must provide."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import StrEnum

from ..config import EngineConfig
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


@dataclass
class HtmlResult:
    html: str
    new_terms: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class EngineError(Exception):
    def __init__(self, message: str, kind: ErrorKind) -> None:
        super().__init__(message)
        self.kind = kind


class Engine(abc.ABC):
    """A translation backend. Instances are long-lived and concurrency-safe."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @property
    @abc.abstractmethod
    def capabilities(self) -> EngineCapabilities: ...

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
