<div align="center">

# 🌐 lncrawl-translator

**Translate entire web novels through one small, stateless API — tuned for Chinese · Korean · Japanese → English.**

[![PyPI](https://img.shields.io/pypi/v/lncrawl-translator?logo=pypi&logoColor=white)](https://pypi.org/project/lncrawl-translator/)
[![Python](https://img.shields.io/pypi/pyversions/lncrawl-translator?logo=python&logoColor=white)](https://pypi.org/project/lncrawl-translator/)
[![Docker](https://img.shields.io/badge/ghcr.io-lncrawl%2Ftranslator-2496ED?logo=docker&logoColor=white)](https://github.com/lncrawl/translator/pkgs/container/translator)
[![CI](https://github.com/lncrawl/translator/actions/workflows/ci.yml/badge.svg)](https://github.com/lncrawl/translator/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/lncrawl/translator/blob/main/LICENSE)

</div>

A translation service for web-novel **metadata** (titles, author, synopsis, tags) and
**HTML chapter content** — markup preserved, only human-readable text translated. Run it
as a standalone container or embed it as a Python library inside your own app.

Built as the stateless translation engine behind
[lightnovel-crawler](https://github.com/lncrawl/lightnovel-crawler), with switchable
engines (free-tier hosted APIs and CPU-friendly local models). Every request can carry a
per-novel glossary that gets injected into translations and returned with any new terms —
so the caller keeps names and terms consistent across thousands of chapters.

---

## ✨ Highlights

|  |  |
|:--|:--|
| 🈶 **CJK → English first** | Purpose-tuned for Chinese/Korean/Japanese source text; other directions work best-effort. |
| 🧾 **Text _and_ HTML** | Batch short strings, or translate a whole chapter's HTML with tags kept intact. |
| 📖 **Glossary-aware** | Pass a glossary in, get new terms out — consistent character/place names at book scale. |
| 🔀 **Switchable engines** | OpenAI-compatible LLMs, DeepL, Baidu, and a **keyless Bing** lane behind one router. |
| ♻️ **Resilient routing** | Client-side rate limiting, retries, cooldowns, and quota-aware failover across lanes. |
| 🎛️ **Live config** | Browser dashboard + CRUD API; edits apply atomically and persist to a sparse YAML overlay. |
| 🧭 **Offline detection** | Unicode-script heuristics + `langdetect` — no network, no engine quota. |
| 🧩 **Standalone or embedded** | Docker/uvicorn service, or a thread-safe synchronous Python facade. |

---

## 🚀 Quick start

No config file needed — a curated set of free providers is pre-wired, and the keyless
**Bing** lane is the default, so translation works even with **zero keys**:

```bash
docker compose up -d
curl http://localhost:8184/health   # shows which engines came up
```

Then open **http://localhost:8184/** and paste your provider API keys — the matching
engines enable instantly, no restart needed.

> 📚 See the [deployment guide](https://github.com/lncrawl/translator/blob/main/docs/deployment.md)
> for engine keys, the keyless Bing lane, and API examples ·
> [design doc](https://github.com/lncrawl/translator/blob/main/docs/design.md) for API &
> architecture · [engine research](https://github.com/lncrawl/translator/blob/main/docs/translation-engines.md).

---

## 🔌 API

| Endpoint | What it does |
|:--|:--|
| `GET /` | Browser demo & config UI — try translations, watch engine status, manage config in place. |
| `GET /health` | Liveness / readiness. |
| `GET /engines` | Configured engines with live status (quota, cooldowns). |
| `POST /detect` | Local language detection (no engine quota). |
| `POST /translate/text` | Batched short strings (titles, tags, synopsis). |
| `POST /translate/html` | One chapter per call — glossary in, new terms out. |
| `GET /config` + CRUD on `/providers`, `/engines`, `/routing` | Runtime config; changes apply atomically and persist to `config.yml`. |

> ⚠️ The API is **unauthenticated by design** — run it on localhost or a private network
> only (see the [deployment guide](https://github.com/lncrawl/translator/blob/main/docs/deployment.md)).

---

## 📦 Use as a library

```bash
pip install lncrawl-translator   # Python 3.9+
```

The embedded service is a thread-safe, synchronous facade that runs the same engine router
on its own event loop:

```python
from translator import TranslatorService

service = TranslatorService(config_path="translator.yml")

service.detect(["どこから来ましたか"])                 # local, no quota
response = service.translate_text({
    "texts": ["少年は勇者になった"],
    "target_lang": "en",
    "glossary": {"勇者": "Hero"},
})
print(response.translations, response.engine, response.new_terms)

service.close()  # on shutdown
```

`translate_text` / `translate_html` accept an optional `signal` (`threading.Event`) for
cooperative cancellation and a `timeout` in seconds.

**Error handling.** Failures share a common `TranslatorError` base, re-exported from the
top-level namespace — map them without importing pydantic or reaching into internals:

```python
from translator import TranslatorError, ApiError, AbortedError, InvalidRequestError
```

Invalid dict payloads raise `InvalidRequestError` (not pydantic's `ValidationError`). Need
only a language code? `from translator import detect_code` returns the bare ISO 639-1 code
(or `None`) without ever constructing a service; `detect_language` is also available.

### Mount the dashboard into a host app

```python
app.mount("/translator", service.create_app())
```

The mounted app shares the service's **live config** — edits in the dashboard apply to the
embedded service immediately. It carries no authentication of its own; the host gates
access.

When the host authenticates the mount, pass `create_app(auth=True)`: the OpenAPI then
declares HTTPBasic **and** HTTPBearer schemes (so the docs' _Authorize_ button works), and
the dashboard reads an admin token from the page's URL fragment (`#token=…`) and sends it
as a Bearer header. The schemes are only _declared_ here — the host still verifies the
credential.

---

## 🛠️ Development

```bash
uv sync
uv run poe check      # ruff + mypy + pytest
uv run poe dev        # dev server with auto-reload
uv run poe start      # production-style server (uvicorn on :8184)
uv run poe live-test  # smoke-test real engines from config.yml (opt-in)
```

See [AGENTS.md](https://github.com/lncrawl/translator/blob/main/AGENTS.md) for project
decisions and conventions, and [CHANGELOG.md](https://github.com/lncrawl/translator/blob/main/CHANGELOG.md)
for release notes.

---

## 📜 License

Licensed under the [Apache License 2.0](https://github.com/lncrawl/translator/blob/main/LICENSE).
