"""Engine protocol: what every translation backend must provide.

A backend declares itself entirely through class attributes and classmethods —
its ``KIND``, the settings and credentials it takes, the capabilities it offers,
and the languages it covers. All of that is answerable *without instantiating*
the engine, which is what lets the registry describe disabled or unconfigured
engines and lets the router gate language pairs before dispatch.

Kind-specific configuration lives in the two settings models a subclass
declares (``PROVIDER_SETTINGS`` / ``ENGINE_SETTINGS``). Those models are the
single source of truth: the config layer stores their data as an opaque dict,
the registry validates it, credential discovery and secret redaction read their
field metadata, and the dashboard renders its forms from their JSON Schema.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .._compat import StrEnum
from ..config import EngineKind, PartialFailurePolicy
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

    Derived from the kind's ``PROVIDER_SETTINGS`` fields marked as credentials;
    ``key`` is the settings key holding the value. Drives the availability gate
    and the dashboard's credential inputs.
    """

    key: str
    label: str
    secret: bool = True
    required: bool = True
    description: str | None = None


class Settings(BaseModel):
    """Base for the per-kind settings models.

    ``extra="forbid"`` is deliberate: it makes a typo in ``config.yml`` or an
    API payload a loud 422 instead of a key that is silently dropped on the
    next save, and it lets the served JSON Schema be authoritative for the
    dashboard's forms.
    """

    model_config = ConfigDict(extra="forbid")


def setting(
    label: str,
    *,
    secret: bool,
    default: Any = None,
    description: str | None = None,
    **kwargs: Any,
) -> Any:
    """Declare a plain (non-credential) settings field.

    Pass ``default=...`` to make the field mandatory, the usual Pydantic
    convention — unlike :func:`credential`, where "required" is about
    availability rather than validation, a plain setting means both at once.

    ``secret`` has no default anywhere in this module on purpose. As ordinary
    Pydantic fields, an endpoint URL and an API token look identical, so a
    forgotten marker would silently expose a token through ``GET /config``.
    Requiring it here, plus the registry's import-time check, makes that
    impossible to get wrong quietly.
    """
    if "default_factory" not in kwargs:
        kwargs["default"] = default
    return Field(
        title=label,
        description=description,
        json_schema_extra={"secret": secret},
        **kwargs,
    )


def credential(
    label: str,
    *,
    secret: bool,
    required: bool = True,
    description: str | None = None,
    **kwargs: Any,
) -> Any:
    """Declare a credential settings field.

    ``required`` means "the engine cannot run without it" — it gates
    availability via :func:`~translator.engines.registry.is_configured`. It is
    *not* Pydantic requiredness: credentials always default to ``None`` so a
    provider can be created before its key is known.
    """
    return Field(
        default=None,
        title=label,
        description=description,
        json_schema_extra={
            "credential": True,
            "secret": secret,
            "required": required,
        },
        **kwargs,
    )


class EngineSettings(Settings):
    """Per-model settings.

    Like :class:`ProviderSettings`, the fields here are what every kind shares;
    a kind subclasses this to add its own (a model name, per-request extras)
    and may *narrow* an inherited one — bing caps the input budget at what the
    service accepts, baidu defaults the target languages to its catalog — so a
    hard limit is a declared constraint rather than a method override, and the
    dashboard renders it from the schema.
    """

    max_input_tokens: int | None = setting(
        "Max input tokens",
        secret=False,
        gt=0,
        description="Context budget for one request. Blank means the engine's"
        " own limit applies.",
    )
    chunk_tokens: int | None = setting(
        "Chunk tokens",
        secret=False,
        gt=0,
        description="Max source tokens per HTML chunk; defaults to a fraction"
        " of the input budget. Lower it for small local models, which stay"
        " coherent on shorter passages.",
    )
    source_langs: list[str] | None = setting(
        "Source languages",
        secret=False,
        description="ISO 639-1 codes this engine may translate from. Blank"
        " means any — which is what LLM lanes use. Setting it makes the router"
        " skip the engine for other languages instead of failing mid-request.",
    )
    target_langs: list[str] | None = setting(
        "Target languages",
        secret=False,
        description="ISO 639-1 codes this engine may translate into. Blank means any.",
    )
    failure_policy: PartialFailurePolicy = setting(
        "Failure policy overrides",
        secret=False,
        default_factory=lambda: PartialFailurePolicy(),
        description="Leave blank to inherit from the provider, which inherits"
        " from the global policy.",
    )


class ProviderSettings(Settings):
    """Account-level settings.

    The fields here are what every kind shares — how hard we may hit the
    account, and what to do when it misbehaves. A kind subclasses this to add
    its endpoint and credentials, so one model describes a whole provider and
    a provider entry needs nothing but an ``id``, a ``kind``, and this.
    """

    requires_key: bool = setting(
        "Requires an API key",
        secret=False,
        default=True,
        description="Uncheck for keyless hosts such as a local server. While a"
        " required credential is missing, this provider's engines stay"
        " disabled.",
    )
    rps: float | None = setting(
        "Requests per second",
        secret=False,
        gt=0,
        description="Client-side pacing shared by every engine on the account."
        " Blank means unlimited.",
    )
    rpm: float | None = setting(
        "Requests per minute",
        secret=False,
        gt=0,
        description="Used when requests per second is blank.",
    )
    max_concurrency: int = setting(
        "Max concurrent requests",
        secret=False,
        default=1,
        ge=1,
        description="How many requests may be in flight on this account at"
        " once. Free tiers often allow only one.",
    )
    failure_policy: PartialFailurePolicy = setting(
        "Failure policy overrides",
        secret=False,
        default_factory=lambda: PartialFailurePolicy(),
        description="Leave blank to inherit the global policy. Anything set"
        " here applies to every engine on this account.",
    )


def field_flag(model: type[BaseModel], name: str, flag: str) -> bool | None:
    """Read one of our ``json_schema_extra`` markers off a settings field."""
    info = model.model_fields.get(name)
    extra = info.json_schema_extra if info is not None else None
    if not isinstance(extra, dict):
        return None
    value = extra.get(flag)
    return value if isinstance(value, bool) else None


S = TypeVar("S", bound=Settings)


def narrow(settings: Settings, expected: type[S]) -> S:
    """Recover the concrete settings type for an engine implementation.

    A generic ``Engine[P, E]`` would be the alternative, but it degrades
    ``dict[EngineKind, type[Engine]]`` in the registry into
    ``type[Engine[Any, Any]]`` and spreads through every signature that takes a
    ``type[Engine]``. A narrowing call in ``__init__`` keeps the blast radius
    at one line per engine.
    """
    if not isinstance(settings, expected):
        raise TypeError(f"expected {expected.__name__}, got {type(settings).__name__}")
    return settings


@dataclass(frozen=True)
class ResolvedEngine:
    """An engine merged with its provider — what engine implementations and the
    router consume, so they never join the two themselves.

    A dataclass rather than a Pydantic model because the settings fields hold
    kind-specific subclasses: a Pydantic field declared ``ProviderSettings``
    serializes a subclass down to the declared type and loses every kind field
    on the way back. This is a pure internal join, never a request or response
    body, so nothing here needs to round-trip through JSON.
    """

    id: str
    provider_id: str
    kind: EngineKind
    enabled: bool
    provider_settings: ProviderSettings
    engine_settings: EngineSettings


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
    # Kind-specific config. Credentials are fields on PROVIDER_SETTINGS; the
    # empty defaults mean "this kind takes nothing beyond the shared fields".
    PROVIDER_SETTINGS: ClassVar[type[ProviderSettings]] = ProviderSettings
    ENGINE_SETTINGS: ClassVar[type[EngineSettings]] = EngineSettings
    # How the backend handles markup, and whether glossary terms are enforced
    # (natively by the provider, or by the substitution this package does).
    HTML: ClassVar[HtmlSupport]
    GLOSSARY: ClassVar[bool] = True

    def __init__(self, config: ResolvedEngine) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @classmethod
    def display_model(cls, config: ResolvedEngine) -> str | None:
        """The model name to show in listings, for kinds that have one."""
        return None

    @classmethod
    def credentials(cls) -> list[CredentialField]:
        """Credentials this kind needs, derived from ``PROVIDER_SETTINGS``.

        Declaration order is preserved, so the engine author controls the order
        of the dashboard's credential inputs.
        """
        fields = []
        for name, info in cls.PROVIDER_SETTINGS.model_fields.items():
            if field_flag(cls.PROVIDER_SETTINGS, name, "credential") is not True:
                continue
            fields.append(
                CredentialField(
                    key=name,
                    label=info.title or name,
                    secret=field_flag(cls.PROVIDER_SETTINGS, name, "secret") is True,
                    required=field_flag(cls.PROVIDER_SETTINGS, name, "required")
                    is not False,
                    description=info.description,
                )
            )
        return fields

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
        A kind with a hard service limit declares it as the field's default and
        upper bound rather than clamping here."""
        return config.engine_settings.max_input_tokens

    @classmethod
    def coverage(
        cls, config: ResolvedEngine
    ) -> tuple[list[str] | None, list[str] | None]:
        """(source, target) base languages covered, ``None`` meaning
        unrestricted. A kind with a finite catalog declares it as the field's
        default."""
        settings = config.engine_settings
        return settings.source_langs, settings.target_langs

    @classmethod
    def supports_pair(
        cls, config: ResolvedEngine, source_lang: str | None, target_lang: str
    ) -> bool:
        """Whether this kind can handle the pair under ``config``. Checked
        before dispatch so the router can skip the engine and reject
        unsupported pairs early."""
        source, target = cls.coverage(config)
        return lang_allowed(source_lang, source) and lang_allowed(target_lang, target)

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
