# Deployment

The service runs as one small container, with an optional llama.cpp sidecar
for the local-model lane. Target: a modest CPU-only VPS (~4 vCPU, 8 GB RAM).

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

## Local model lane (optional)

1. Download a GGUF into `./models/` — recommended default is Qwen3.5-4B at
   Q4_K_M (~2.5–3.3 GB file, ~5 GB RAM in use):

   ```bash
   mkdir -p models
   curl -L -o models/model.gguf \
     "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf"
   ```

2. Uncomment the `local-qwen` engine in `config.yml` and add it to the
   routing lanes (typically last, as the fallback).

3. Start with the profile enabled:

   ```bash
   docker compose --profile local up -d
   ```

Tuning for a small VPS:

- `--threads` should equal your **physical** core count (compose default: 4).
- `--ctx-size 8192` fits a chapter + glossary; the router chunks anything
  bigger.
- Prefer the **MTP variant GGUF** (e.g. `unsloth/Qwen3.5-4B-MTP-GGUF`):
  llama.cpp uses the multi-token-prediction head as built-in speculative
  decoding for a 1.4–2x decode speedup at identical quality.
- Add `-fa` (flash attention) and `--cache-type-k q8_0 --cache-type-v q8_0`
  for modest extra speed and lower RAM.
- Expect very roughly 10–25 tok/s → ~2–5 min per chapter → 300–800
  chapters/day. That is the local lane's job: slow, free, always available.
- A 9B model at Q4 (~6.5 GB) also fits but leaves little headroom next to
  the service; only use it if nothing else runs on the box. Benchmark first
  with `llama-bench` before committing to a model.

Note for local testing on a Mac: Docker on macOS runs in a VM and Apple
offers no Metal passthrough, so llama.cpp inside compose is CPU-only and
slow. Two GPU-accelerated alternatives:

- **Native llama-server**: `brew install llama.cpp`, then
  `llama-server -m model.gguf -ngl 99 --port 8080` uses Metal directly —
  typically several times faster. Point the engine's `base_url` at
  `http://host.docker.internal:8080/v1` from compose, or
  `http://localhost:8080/v1` when running the translator via
  `uv run poe dev`.
- **Docker Model Runner**: enable it in Docker Desktop (Features → Docker
  Model Runner), `docker model pull` a model, and add an engine with
  `base_url: http://model-runner.docker.internal/engines/v1`. It runs
  llama.cpp on the host with Metal (outside the VM) while staying
  addressable from containers.

The service reaches the sidecar at `http://llamacpp:8080/v1` (already the
`base_url` of the commented-out engine in the example config). llama.cpp
serves whatever model it loaded regardless of the `model` value sent.

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
