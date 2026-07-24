# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-07-24

### Fixed

- `BingEngine` no longer binds an `asyncio.Lock` at construction; on
  Python 3.9 this crashed (or bound to the wrong loop) when the embedded
  `TranslatorService` was first constructed from a non-main host thread.

### Added

- `py.typed` marker so type checkers use the package's annotations.

## [0.1.0] - 2026-07-24

First release.

### Added

- Stateless translation service for web novels: `POST /translate/text` for
  batched short strings and `POST /translate/html` for whole chapters, with
  per-request glossaries in and newly extracted terms out so callers can keep
  names consistent across thousands of chapters.
- Switchable engines behind one router: OpenAI-compatible LLM endpoints,
  DeepL, Bing (keyless), and Baidu — with routing lanes, client-side rate
  limiting, provider-shared concurrency, retries, cooldowns, and quota-aware
  failover.
- Providers/engines/routing managed at runtime through a browser dashboard
  and CRUD API; changes apply atomically and persist to a sparse YAML overlay
  on the built-in defaults.
- Local language detection (`POST /detect`): Unicode-script heuristics for
  CJK plus a seeded `langdetect` fallback — no network, no engine quota.
- Embedded mode for host applications: `TranslatorService`, a thread-safe
  synchronous facade running the engine router on a dedicated event-loop
  thread, with cooperative cancellation and timeouts;
  `service.create_app()` mounts the dashboard sharing the live config.
- Standalone deployment via Docker (`ghcr.io/lncrawl/translator`) or the
  `server` extra (`uvicorn translator.main:app`).
- Python 3.9+ support.
