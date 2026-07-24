# Deployment

The service runs as one small container with no local ML stack — every lane
is a hosted API or the keyless Bing endpoint. Target: a modest CPU-only VPS
(~1 vCPU, 512 MB RAM is plenty).

## Quick start

No config file is needed — the built-in defaults pre-wire a curated set of
free providers, and the keyless Bing lane works immediately. API keys are
configured remotely after boot:

```bash
docker compose up -d                 # pulls ghcr.io/lncrawl/translator:latest
curl http://localhost:8184/health    # lists which engines came up
```

Then open http://localhost:8184/ and paste your provider API keys in the
Providers table (or `PATCH /providers/{id}` with `{"api_key": "..."}`) —
the matching engines enable instantly, no restart needed.

The API has no authentication — see "Security" below before running it
anywhere other than localhost or a private network.

Prebuilt images (amd64 + arm64) are published to
`ghcr.io/lncrawl/translator` on every push to main (`latest`, `sha-…`) and
on version tags (`1.2`, `1.2.3`). Use `docker compose up -d --build` to
build from source instead.

## Customizing the config

Three options, all optional:

- **Runtime config API** (recommended): change providers, engines, routing,
  or the failure policy over HTTP — see "Runtime config API" below. The
  first write creates `/data/config.yml` (persisted in the compose volume).
- **Own file**: bind-mount a directory over `/data` with a `config.yml` in
  it, or point `$TRANSLATOR_CONFIG` at a file elsewhere.
- **Local dev**: a `./config.yml` in the working directory is picked up
  automatically; without one, the same built-in defaults apply.

### The config file is a sparse overlay

`config.yml` is **not** a full snapshot — it is a sparse overlay on the
built-in defaults (`translator/defaults.py`). On load, its entries merge onto
the defaults **by id**, so you list only what you change; everything you omit
falls back to the default. This is what keeps the file from going stale: when
a new default provider/engine is added (or an existing one's model id or rate
limits change) in a new release, it flows into your install automatically
instead of being frozen at whatever the file first captured.

The API and web UI write this same overlay back, so a hand-edited file and a
UI-managed one stay in the same minimal shape. A typical file is just a few
keys:

```yaml
# Paste keys for default providers you use — base_url, limits, etc. are
# inherited from the default of the same id. The matching engines enable
# themselves. Override any inherited field by adding it here.
providers:
  - id: zai
    api_key: "your-z.ai-key"
  - id: gemini
    api_key: "your-ai-studio-key"
  # baidu takes two named credentials instead of a single api_key:
  # - id: baidu
  #   options: {app_id: "...", secret_key: "..."}
```

Other overlay operations:

- **Add your own provider/engine** — give it a new id; custom entries are
  listed in full. A local OpenAI-compatible server (llama.cpp, Ollama) needs
  no key:
  ```yaml
  providers:
    - id: local-llm
      kind: openai
      base_url: http://localhost:8080/v1
      requires_key: false
  engines:
    - id: local-qwen
      provider: local-llm
      model: qwen3.5-4b
      max_input_tokens: 32000
  ```
- **Override one field** of a default engine (the rest is inherited):
  ```yaml
  engines:
    - id: gemini-flash
      max_input_tokens: 100000 # smaller context than the default
  ```
- **Drop a default** you never want, by id (a removed provider takes its
  engines with it):
  ```yaml
  removed_providers: [groq]
  removed_engines: [groq-oss]
  ```
- **Reorder/restrict a routing lane** — only the lanes you list change; omit
  `routing` to keep the default order (keyless Bing first, then the keyed LLM
  lanes):
  ```yaml
  routing:
    chapter: [gemini-flash, bing]
  ```

Legacy flat configs (engines carrying `base_url`/`kind` inline instead of a
`provider` reference) predate the overlay format and are loaded standalone —
defaults are not merged into them.

## Engine keys

Provider API keys are set remotely — web UI at `/` or
`PATCH /providers/{id} {"api_key": "..."}` — and persist in
`/data/config.yml`. Pre-wired providers and where to sign up:

| Provider | Where to get a key                                                        |
| -------- | ------------------------------------------------------------------------- |
| `gemini` | https://aistudio.google.com — free tier (~1,500 req/day), volatile quotas |
| `groq`   | https://console.groq.com — free, no card; small daily token cap           |

`bing` (Microsoft Translator via Edge's keyless endpoint) is the default lane
and needs no key — the service translates out of the box with zero accounts.
The pre-wired `local-llm` provider is also keyless (it points at a local
OpenAI-compatible server).

Add any other OpenAI-compatible provider (DeepSeek, Cloudflare Workers AI…)
as a new `kind: openai` provider via the config API or UI — no code changes;
local servers that need no key take `requires_key: false`. Engines whose
provider has no key yet are auto-disabled and shown as such in `GET /engines`.

Keys live in the config file and are returned by `GET /config`, so keep
the service on a private network and the file out of version control.

## Local LLM lane (optional)

The service ships no in-process model — it stays a thin HTTP client, so the
container is small and CPU-only with no ML stack. For an offline/local lane,
run an OpenAI-compatible server (Docker Model Runner, llama.cpp, Ollama, LM
Studio) and use the pre-wired `local-llm` provider (or add your own). The
default config includes a disabled `qwen3.5-4B` engine as a template — pull a
model into your runner, point `model` at it, enable it, and add it to a
routing lane:

```bash
PATCH /engines/qwen3.5-4B {"enabled": true, "model": "<your-pulled-model>"}
```

An instruction-following local LLM applies the glossary and context, unlike a
plain NMT model would.

## Security

The API is completely open — no authentication. It is designed for
localhost or a trusted internal network only. Anyone who can reach the
port can translate, read provider API keys via `GET /config`, and change
the config. Never expose port 8184 to the internet; if remote access is
needed, put it behind a reverse proxy that handles auth + TLS.

## Runtime config API

Providers, engines, routing, and the failure policy can be changed at
runtime — changes are validated as a whole, applied atomically (a new router
is swapped in; in-flight requests finish on the old one), and written back
to `config.yml`.

```bash
# Read the live config
curl -s http://localhost:8184/config

# Set a provider's API key (enables its engines instantly)
curl -s -X PATCH http://localhost:8184/providers/zai \
  -H 'Content-Type: application/json' \
  -d '{"api_key": "your-key"}'

# Swap a model in place
curl -s -X PATCH http://localhost:8184/engines/zai-glm-flash \
  -H 'Content-Type: application/json' \
  -d '{"model": "glm-5-flash"}'

# Add a second model on an existing provider (shares its rate limits).
# New engines are not routed automatically; add them to a lane via PUT /routing.
curl -s -X POST http://localhost:8184/engines \
  -H 'Content-Type: application/json' \
  -d '{"id": "or-qwen", "provider": "openrouter", "model": "qwen/qwen3.5-235b-a22b:free"}'

# Reorder lanes (and add newly created engines)
curl -s -X PUT http://localhost:8184/routing \
  -H 'Content-Type: application/json' \
  -d '{"chapter": ["or-qwen", "zai-glm-flash"], "short_text": ["zai-glm-flash"]}'
```

Endpoints: `GET /config`, `PUT /config`, `PUT /config/failure-policy`,
`PUT /routing`, `POST/PATCH/DELETE /providers[/{id}]`,
`POST/PATCH/DELETE /engines[/{id}]`. Routing lanes are configured manually via
`PUT /routing`; creating an engine never adds it to a lane, while deleting an
engine removes it from the lanes; deleting a provider requires deleting its
engines first.

Note: the compose file mounts `config.yml` read-write so API changes
persist across restarts.

## Failure handling

- **Busy engine** (its provider's `max_concurrency` slots are all in use):
  skipped in favor of the next lane engine that can start immediately, so
  load spills down the lane instead of queueing behind the top engine. If
  _every_ eligible engine is busy the request waits, in lane order — it is
  never rejected just for being busy.
- **Transient errors** (5xx, timeouts, 429 with a short `Retry-After`):
  retried on the same engine with exponential backoff
  (`failure_policy.transient_retries`, default 2).
- **Quota errors** (long 429, 402, DeepL 456): the whole _provider_ is
  benched until the reset time — all its models skip together.
- **Repeated failures**: after `failure_threshold` consecutive failed
  requests (default 3) an engine is benched for `cooldown_seconds`
  (default 300) instead of being retried first-in-lane on every request.
- `GET /engines` shows per-engine `status` (`ok`, `quota_exhausted`,
  `error`, `disabled`) and `retry_at` — when a benched engine is eligible
  again.

## Operations

- `LOG_LEVEL` (default `INFO`) controls application log verbosity, e.g.
  `LOG_LEVEL=DEBUG` or `LOG_LEVEL=WARNING`.
- `source_lang` / `target_lang` are BCP 47 tags: an ISO 639-1 code plus an
  optional script/region subtag, case-insensitive (`zh`, `zh-TW`, `zh-Hant`,
  `pt-BR`). Region aliases collapse to scripts (`zh-TW` → `zh-Hant`); invalid
  tags are rejected with `422`.
- Request payloads are capped: 10 MB per request body (`413`), 1,000,000
  characters of HTML per chapter, 10,000 characters per text item, 5,000 per
  context field (`422`).

## Sanity checks

```bash
# Engine status, including quota state
curl -s http://localhost:8184/engines | python3 -m json.tool

# Language detection (free, no engine quota)
curl -s http://localhost:8184/detect \
  -H 'Content-Type: application/json' \
  -d '{"texts": ["斗破苍穹"]}'

# Chapter translation with glossary pass-through
curl -s http://localhost:8184/translate/html \
  -H 'Content-Type: application/json' \
  -d '{
    "html": "<p>萧炎盯着面前的老者。</p>",
    "target_lang": "en",
    "glossary": {"萧炎": "Xiao Yan"},
    "context": {"novel_title": "Battle Through the Heavens"}
  }'
```

Callers should use long HTTP timeouts (up to ~15 min when the local lane
handles a chapter) and treat `503` + `Retry-After` as "pause and resume
later", not failure — it means every configured lane is quota-exhausted
until the indicated time.
