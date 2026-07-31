# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-07-31

### Changed

- **Config shape**: everything specific to an engine kind now lives in an entry's `settings` object, declared by the kind's own Pydantic models and served as JSON Schema at `GET /schema`. Providers are `{id, kind, settings}`, engines `{id, provider, enabled, settings}`. Files and PATCH bodies using the old flat keys (`api_key`, `base_url`, `model`, …) still load and are rewritten on the next save, but are deprecated. Unknown settings keys are rejected.
- The failure policy can now be overridden per provider and per engine, resolved engine > provider > global.

### Removed

- **DeepL no longer takes a `base_url`** — the endpoint is derived from the key (`:fx` selects the free host). A config that sets it is now rejected; delete the key to load.
- `monthly_chars`, which nothing read. It is dropped from older files on load.
- Bing's `max_input_tokens` is bounded by what the service accepts (20k) rather than silently clamped, so a config asking for more is now rejected.

## [0.2.1] - 2026-07-25

- Add PyPI classifiers and keywords
- Reorganize the package into layered subpackages
- Redact credentials before sending them via APIs

## [0.2.0] - 2026-07-24

### Added

- Public exception taxonomy under a common `TranslatorError` base, re-exported from the top-level `translator` namespace: `TranslatorError`, `ApiError`, `AbortedError`, and the new `InvalidRequestError`. Embedding hosts can now map translator errors without importing pydantic or reaching into internal modules. The sync `TranslatorService.translate_text`/`translate_html` methods raise `InvalidRequestError` (instead of leaking pydantic's `ValidationError`) when a dict payload fails validation.
- `detect_code(text) -> str | None`: a free function returning the bare ISO 639-1 code (or `None` for `"und"`), for callers that only want the code. Stays loop-free — it never constructs a `TranslatorService`.
- The response models `TranslateTextResponse` / `TranslateHtmlResponse` are now re-exported from the top-level `translator` namespace (for host typing).

### Changed

- `AbortedError` now subclasses `TranslatorError` rather than `RuntimeError`. It remains importable from `translator.service` for backward compatibility.

## [0.1.3] - 2026-07-24

### Added

- Embedded auth (`create_app(auth=True)`) now also declares an HTTPBasic scheme alongside HTTPBearer, so the docs' Authorize dialog offers both — matching hosts that accept either credential.

## [0.1.2] - 2026-07-24

### Added

- Optional auth for embedded mode: `create_app(auth=True)` declares an `HTTPBearer` scheme so the mounted dashboard's docs show an Authorize button, and the dashboard reads an admin token from the page's URL fragment (`#token=…`) and sends it as a Bearer header on its API calls. The token is not enforced here — the mounting host verifies it. Standalone use is unchanged (unauthenticated).

### Fixed

- `__version__` is now read from the installed package metadata instead of a hardcoded constant, which had drifted (the 0.1.1 release reported `0.1.0`).

## [0.1.1] - 2026-07-24

### Fixed

- `BingEngine` no longer binds an `asyncio.Lock` at construction; on Python 3.9 this crashed (or bound to the wrong loop) when the embedded `TranslatorService` was first constructed from a non-main host thread.

### Added

- `py.typed` marker so type checkers use the package's annotations.

## [0.1.0] - 2026-07-24

First release.

### Added

- Stateless translation service for web novels: `POST /translate/text` for batched short strings and `POST /translate/html` for whole chapters, with per-request glossaries in and newly extracted terms out so callers can keep names consistent across thousands of chapters.
- Switchable engines behind one router: OpenAI-compatible LLM endpoints, DeepL, Bing (keyless), and Baidu — with routing lanes, client-side rate limiting, provider-shared concurrency, retries, cooldowns, and quota-aware failover.
- Providers/engines/routing managed at runtime through a browser dashboard and CRUD API; changes apply atomically and persist to a sparse YAML overlay on the built-in defaults.
- Local language detection (`POST /detect`): Unicode-script heuristics for CJK plus a seeded `langdetect` fallback — no network, no engine quota.
- Embedded mode for host applications: `TranslatorService`, a thread-safe synchronous facade running the engine router on a dedicated event-loop thread, with cooperative cancellation and timeouts; `service.create_app()` mounts the dashboard sharing the live config.
- Standalone deployment via Docker (`ghcr.io/lncrawl/translator`) or the `server` extra (`uvicorn translator.main:app`).
- Python 3.9+ support.

[0.2.2]: https://github.com/lncrawl/scraper/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/lncrawl/scraper/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/lncrawl/scraper/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/lncrawl/scraper/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/lncrawl/scraper/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/lncrawl/scraper/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lncrawl/scraper/releases/tag/v0.1.0
