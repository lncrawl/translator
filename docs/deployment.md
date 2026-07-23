# Deployment

The service runs as one small container; the local-model fallback (NLLB)
runs in-process, so nothing else is needed. Target: a modest CPU-only VPS
(~4 vCPU, 8 GB RAM).

## Quick start

No config file is needed — the built-in defaults pre-wire every known
free provider, and an engine activates as soon as its key env var is set:

```bash
export ZAI_API_KEY=...               # whichever keys you have
export AUTH_TOKEN=...                # optional; omit on a private network

docker compose up -d                 # pulls ghcr.io/lncrawl/translator:latest
curl http://localhost:8000/health    # lists which engines came up
```

Prebuilt images (amd64 + arm64) are published to
`ghcr.io/lncrawl/translator` on every push to main (`latest`, `sha-…`) and
on version tags (`1.2`, `1.2.3`). Use `docker compose up -d --build` to
build from source instead.

## Customizing the config

Three options, all optional:

- **Runtime config API** (recommended): change providers, engines, routing,
  or the failure policy over HTTP — see "Runtime config API" below. The
  first write creates `/data/config.yml` (persisted in the compose volume),
  which then takes precedence over the built-in defaults on every boot.
- **Own file**: bind-mount a directory over `/data` with a `config.yml` in
  it (start from `config.example.yml`), or point `$TRANSLATOR_CONFIG` at a
  file elsewhere.
- **Local dev**: a `./config.yml` in the working directory is picked up
  automatically; without one, the same built-in defaults apply.

## Engine keys

| Env var | Where to get it |
|---|---|
| `ZAI_API_KEY` | https://z.ai — GLM-4.7-Flash is free with no token cap |
| `GEMINI_API_KEY` | https://aistudio.google.com — free tier, volatile quotas |
| `DEEPL_API_KEY` | https://www.deepl.com/pro-api — Free plan, 500K chars/mo (key ends in `:fx`) |

The built-in defaults also know `CEREBRAS_API_KEY`, `MISTRAL_API_KEY`,
`GROQ_API_KEY`, and `OPENROUTER_API_KEY`. Add any other OpenAI-compatible
provider (DeepSeek, ModelScope…) as a new `kind: openai` provider via the
config API or config file — no code changes. Engines whose provider key env
is unset are auto-disabled and shown as such in `GET /engines`.

## Local model lane (built in)

The last lane in the default routing is `nllb` — Meta's NLLB-200 NMT model
(distilled 1.3B, int8) running in-process on CPU via CTranslate2. It needs
no API key, so translation works out of the box even with zero provider
accounts.

- The model (~1.4 GB) is downloaded from Hugging Face on the first request
  that reaches the lane and cached under `$HF_HOME` (`/data/hf-cache` in the
  container, inside the compose volume) — later boots reuse it.
- It is sentence-level NMT: fast and always available, but no glossary,
  context, or instruction following. HTML is handled by the service's
  segment extraction, so markup is preserved.
- Memory: ~2 GB resident while loaded; fits alongside the service on an
  8 GB box.
- To change quality/speed: swap `model` to another CTranslate2 conversion —
  `OpenNMT/nllb-200-3.3B-ct2-int8` for best NLLB quality (slow on CPU), or
  the community `JustFrederik/nllb-200-distilled-600M-ct2-int8` for half
  the size and ~2x speed — or raise `extra_body.beam_size` (default 2) for
  slightly better output at proportional cost.
- To disable it (e.g. on a tiny box where the download/RAM is unwelcome):
  `PATCH /engines/nllb {"enabled": false}` or remove it from the routing
  lanes.

An OpenAI-compatible local server (llama.cpp, Ollama, Docker Model Runner)
can still be added as a regular `kind: openai` provider pointing at its URL
if you want an instruction-following local LLM lane instead.

## Security

- Set `AUTH_TOKEN` unless the service is only reachable from localhost or a
  private network; callers then need `Authorization: Bearer <token>`.
- `/health` is always unauthenticated (container health checks use it).
- Don't expose port 8000 publicly without a reverse proxy + TLS.

## Runtime config API

Providers, engines, routing, and the failure policy can be changed at
runtime — changes are validated as a whole, applied atomically (a new router
is swapped in; in-flight requests finish on the old one), and written back
to `config.yml`.

Writes require `Authorization: Bearer $ADMIN_TOKEN` (falls back to
`AUTH_TOKEN`; when neither is set, writes are disabled with `403`).

```bash
# Read the live config (regular auth)
curl -s http://localhost:8000/config

# Swap a model in place
curl -s -X PATCH http://localhost:8000/engines/zai-glm-flash \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model": "glm-5-flash"}'

# Add a second model on an existing provider (shares its rate limits)
curl -s -X POST http://localhost:8000/engines \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"id": "or-qwen", "provider": "openrouter", "model": "qwen/qwen3.5-235b-a22b:free"}'

# Reorder lanes
curl -s -X PUT http://localhost:8000/routing \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"chapter": ["or-qwen", "zai-glm-flash"], "short_text": ["zai-glm-flash"]}'
```

Endpoints: `GET /config`, `PUT /config`, `PUT /config/failure-policy`,
`PUT /routing`, `POST/PATCH/DELETE /providers[/{id}]`,
`POST/PATCH/DELETE /engines[/{id}]`. Deleting an engine also removes it from
routing lanes; deleting a provider requires deleting its engines first.
API keys are never sent through this API — providers reference env var
names, and keys stay in the environment.

Note: the compose file mounts `config.yml` read-write so API changes
persist across restarts.

## Failure handling

- **Transient errors** (5xx, timeouts, 429 with a short `Retry-After`):
  retried on the same engine with exponential backoff
  (`failure_policy.transient_retries`, default 2).
- **Quota errors** (long 429, 402, DeepL 456): the whole *provider* is
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
curl -s http://localhost:8000/engines | python3 -m json.tool

# Language detection (free, no engine quota)
curl -s http://localhost:8000/detect \
  -H 'Content-Type: application/json' \
  -d '{"texts": ["斗破苍穹"]}'

# Chapter translation with glossary pass-through
curl -s http://localhost:8000/translate/html \
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
