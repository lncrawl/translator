# translator

A Docker service that translates entire lightnovels/webnovels — metadata
(titles, author, synopsis, tags) and HTML chapter content — with a focus on
Chinese / Korean / Japanese → English.

Built as a stateless translation API for
[lightnovel-crawler](https://github.com/dipu-bd/lightnovel-crawler), with
switchable translation engines (free-tier hosted APIs and CPU-friendly local
models). Requests can carry a per-novel glossary that is injected into
translations and returned with new terms, so the caller can maintain name/term
consistency across thousands of chapters.

## Quick start

No config file needed — every known free provider is pre-wired, and an
engine activates when its key env var is set:

```bash
export ZAI_API_KEY=...             # whichever keys you have
docker compose up -d
curl http://localhost:8000/health  # shows which engines came up
```

See [docs/deployment.md](docs/deployment.md) for engine keys, the optional
local-model lane, and API examples; [docs/design.md](docs/design.md) for the
API and architecture; [docs/translation-engines.md](docs/translation-engines.md)
for the engine research.

## API

- `GET /health` — liveness/readiness
- `GET /engines` — configured engines with live status (quota, cooldowns)
- `POST /detect` — local language detection (no engine quota)
- `POST /translate/text` — batched short strings (titles, tags, synopsis)
- `POST /translate/html` — one chapter per call, glossary in/new terms out
- `GET /config` + CRUD on `/providers`, `/engines`, `/routing` — runtime
  config management; changes apply atomically and persist to `config.yml`
  (writes need `ADMIN_TOKEN`, see
  [docs/deployment.md](docs/deployment.md))

## Development

```bash
uv sync
uv run poe check      # ruff + mypy + pytest
uv run poe dev        # dev server with auto-reload
uv run poe start      # production-style server (uvicorn on :8000)
uv run poe live-test  # smoke-test real engines from config.yml (opt-in)
```

See [AGENTS.md](AGENTS.md) for project decisions and conventions.
