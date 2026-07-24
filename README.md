# lncrawl-translator

A web-novel translation service — metadata (titles, author, synopsis, tags)
and HTML chapter content — with a focus on Chinese / Korean / Japanese →
English. Runs standalone (Docker/uvicorn) or embedded as a Python library
inside a host application.

Built as a stateless translation API for
[lightnovel-crawler](https://github.com/dipu-bd/lightnovel-crawler), with
switchable translation engines (free-tier hosted APIs and CPU-friendly local
models). Requests can carry a per-novel glossary that is injected into
translations and returned with new terms, so the caller can maintain name/term
consistency across thousands of chapters.

## Quick start

No config file needed — a curated set of free providers is pre-wired, and the
keyless Bing lane (no key required) is the default, so translation works even
with zero keys:

```bash
docker compose up -d
curl http://localhost:8184/health  # shows which engines came up
```

Then open http://localhost:8184/ and paste your provider API keys — the
matching engines enable instantly, no restart needed.

See [docs/deployment.md](docs/deployment.md) for engine keys, the keyless
Bing lane, and API examples; [docs/design.md](docs/design.md) for the
API and architecture; [docs/translation-engines.md](docs/translation-engines.md)
for the engine research.

## API

- `GET /` — browser demo & config UI: try translations, watch engine
  status, and manage the runtime config without leaving the page
- `GET /health` — liveness/readiness
- `GET /engines` — configured engines with live status (quota, cooldowns)
- `POST /detect` — local language detection (no engine quota)
- `POST /translate/text` — batched short strings (titles, tags, synopsis)
- `POST /translate/html` — one chapter per call, glossary in/new terms out
- `GET /config` + CRUD on `/providers`, `/engines`, `/routing` — runtime
  config management; changes apply atomically and persist to `config.yml`

The API is unauthenticated by design — run it on localhost or a private
network only (see [docs/deployment.md](docs/deployment.md)).

## Use as a library

Install the package (`pip install lncrawl-translator`; Python 3.9+) and use
the embedded service — a thread-safe, synchronous facade that runs the same
engine router on its own event loop:

```python
from translator import TranslatorService

service = TranslatorService(config_path="translator.yml")

service.detect(["どこから来ましたか"])                # local, no quota
response = service.translate_text({
    "texts": ["少年は勇者になった"],
    "target_lang": "en",
    "glossary": {"勇者": "Hero"},
})
print(response.translations, response.engine, response.new_terms)

service.close()  # on shutdown
```

`translate_text`/`translate_html` accept an optional `signal`
(`threading.Event`) for cooperative cancellation and a `timeout` in seconds.

The dashboard and HTTP API can be mounted into a host ASGI app, sharing the
service's live config — edits made in the dashboard apply to the embedded
service immediately:

```python
app.mount("/translator", service.create_app())
```

The mounted app carries no authentication (same as the standalone server) —
the host must gate access itself. Language detection is also available
without a service: `from translator import detect_language`.

## Development

```bash
uv sync
uv run poe check      # ruff + mypy + pytest
uv run poe dev        # dev server with auto-reload
uv run poe start      # production-style server (uvicorn on :8184)
uv run poe live-test  # smoke-test real engines from config.yml (opt-in)
```

See [AGENTS.md](AGENTS.md) for project decisions and conventions.
