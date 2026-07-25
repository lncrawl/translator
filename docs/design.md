# Service Design

A stateless HTTP translation service for web novels, consumed by lncrawl
(which owns novel storage, orchestration, and the glossary between calls).

## Goals recap

- Translate short texts (titles, author, tags, synopsis) and HTML chapter
  bodies (~2,000 words), best quality for ZH/JA/KO→EN.
- Zero cost by default: keyless Bing + free hosted lanes, switchable by config.
- Fully stateless: glossary arrives in the request, returns (extended) in the
  response.
- Batch-friendly: built around free-tier rate limits, not speed.

## API surface

All endpoints are synchronous JSON over HTTP. Chapter translation can take
seconds (hosted LLM) to ~10 minutes (local CPU model) — callers must use long
client timeouts (lncrawl calls server-to-server, typically on the same host).
No authentication — the service targets localhost/private-network
deployments only.

### `GET /health`

Liveness + readiness (at least one engine configured and not quota-dead).

### `GET /engines`

Lists configured engines with capabilities and live status:

```json
{
  "engines": [
    {
      "id": "zai-glm-flash",
      "provider": "zai",
      "kind": "openai",
      "model": "glm-4.7-flash",
      "enabled": true,           // enabled in config and its provider is keyed
      "capabilities": {"html": "prompt", "glossary": true, "max_input_tokens": 200000,
                       "source_langs": null, "target_langs": null},
      "status": "ok",            // ok | throttled | quota_exhausted | error | disabled
      "retry_at": null,          // when a benched engine becomes eligible again
      "slots_free": 4,           // provider concurrency, shared by its engines
      "slots_total": 4
    }
  ]
}
```

### `POST /detect`

Standalone language detection — e.g. lncrawl classifying a novel on import.
Runs locally in the service (script heuristics + a small statistical
detector), costs no engine quota, and works on plain text or HTML (tags are
stripped before detection).

```json
// request
{"texts": ["斗破苍穹", "<p>소설 내용…</p>"]}
// response
{
  "results": [
    {"language": "zh", "confidence": 0.99},
    {"language": "ko", "confidence": 0.97}
  ]
}
```

Short strings (a lone title) can be ambiguous — e.g. kanji-only Japanese
titles are indistinguishable from Chinese — so `confidence` is honest and the
caller should prefer detecting on chapter-sized text when available.

### `POST /translate/text`

Short strings: novel/volume/chapter titles, author, tags, synopsis. Batched —
one call translates many strings (a whole chapter-title list can be split
into a few calls by the client, or sent in one; the service chunks internally
to fit engine limits).

```json
// request
{
  "texts": ["斗破苍穹", "萧炎", "第一章 陨落的天才"],
  "source_lang": "zh",          // optional, auto-detect if omitted
  "target_lang": "en",          // default "en"
  "glossary": {"萧炎": "Xiao Yan"},              // optional
  "context": "Chinese xianxia novel titles",     // optional hint
  "engine": "zai-glm-flash"                      // optional override; default: routing config
}
// response
{
  "translations": ["Battle Through the Heavens", "Xiao Yan", "Chapter 1: The Fallen Genius"],
  "detected_source_lang": "zh",
  "engine": "zai-glm-flash",
  "new_terms": {}               // terms the engine identified (may be empty)
}
```

### `POST /translate/html`

One chapter body per call.

```json
// request
{
  "html": "<p>萧炎盯着面前的老者……</p><p>……</p>",
  "source_lang": "zh",
  "target_lang": "en",
  "glossary": {"萧炎": "Xiao Yan", "斗气": "Dou Qi"},
  "context": {                  // all optional; improves quality
    "novel_title": "Battle Through the Heavens",
    "synopsis": "…",
    "chapter_title": "第一章 陨落的天才",
    "previous_chapter_tail": "…last ~500 chars of previous translated chapter…"
  },
  "engine": null,
  "extract_terms": true         // default true; set false to skip glossary extraction
}
// response
{
  "html": "<p>Xiao Yan stared at the old man before him…</p><p>…</p>",
  "detected_source_lang": "zh",
  "engine": "zai-glm-flash",
  "new_terms": {"药老": "Yao Lao"},   // discovered proper nouns + chosen translations
  "warnings": []                       // e.g. "tag structure repaired", "chunked into 3 parts"
}
```

The caller merges `new_terms` into its stored glossary and sends the merged
map with the next chapter — that loop is what keeps names consistent across
thousands of chapters.

### Errors

Structured error body everywhere:

```json
{"error": {"code": "all_engines_exhausted", "message": "…", "retry_after_seconds": 3600}}
```

- `422` invalid request; `502` engine failure after retries;
  `503` + `Retry-After` when all eligible lanes are quota-exhausted or
  throttled. Quota exhaustion is a first-class signal, not a generic error —
  lncrawl schedules around it.

## Language detection

Used by `/detect` and by the translate endpoints when `source_lang` is
omitted (the result is echoed back as `detected_source_lang`). Two layers:

1. **Script heuristics** — Unicode-range analysis separates hangul (ko),
   kana (ja), and hanzi-only text cheaply and near-perfectly for KO/JA;
   hanzi-only text is ambiguous between zh and ja.
2. **Statistical detector** — a small pure-Python local library
   (`langdetect`, seeded for determinism) resolves ambiguous cases and
   covers non-CJK languages.

No network call, no engine quota. HTML input is text-extracted first.

## Code structure

The package is layered top-down; each layer only imports from the ones below
it, so the translation core runs identically with or without the HTTP server.

```
translator/            public surface: schemas (the translation contract),
                       errors, service (embedded sync facade), main
 ├─ server/            FastAPI app, routes/ (one module per resource), deps,
 │                     dto (HTTP-only shapes), secrets, dashboard static/
 ├─ core/              router (which engine, and what on failure)
 │                     pipeline (the workflow around an engine call)
 │                     limits (provider/engine health) · store (live config)
 ├─ engines/           one class per kind, reached via registry
 │                     base (protocol, settings models) · http (shared client)
 │                     registry (kind table, resolution, validation) · prompts
 ├─ text/              html · languages · detect · glossary  (pure helpers)
 └─ config/            models · defaults · overlay · io · legacy (deletable)
```

## Engine abstraction

An engine class declares everything about its kind — no lookup table anywhere
else has to be kept in sync with it. Its two Pydantic settings models are the
single source of truth for the kind's configuration: the config layer stores
their data as an opaque `settings` dict, the registry validates it, secret
redaction reads their field metadata, and the dashboard renders its forms from
their JSON Schema at `GET /schema`:

```
Engine (protocol)
 ├─ KIND, HTML, GLOSSARY                         # class-level declarations
 ├─ PROVIDER_SETTINGS, ENGINE_SETTINGS           # the kind's own config models,
 │                                               #   extending the shared bases
 │                                               #   and free to narrow a field
 ├─ credentials() -> [CredentialField]           # derived from PROVIDER_SETTINGS
 ├─ describe(config) -> capabilities             # answerable without an instance,
 ├─ coverage(config) -> (source, target langs)   #   so disabled engines can still
 ├─ supports_pair(config, src, tgt) -> bool      #   be listed and gated
 ├─ async translate_segments(segments, src, tgt, glossary, context) -> segments
 ├─ async translate_html(html, ...) -> HtmlResult   # only if HTML != none
 └─ classify_http_error(response) -> transient | quota | fatal

Implementations (registry.py maps kind -> class)
 ├─ OpenAICompatEngine — covers Z.AI, Cerebras, Mistral, Groq, OpenRouter,
 │   DeepSeek, ModelScope, Gemini (via its OpenAI-compat endpoint), and any
 │   local OpenAI-compatible server. One class, config-only differences.
 ├─ DeepLEngine — native HTML mode; terms forced by substitution.
 ├─ BingEngine — Microsoft Translator via Edge's keyless endpoint; the
 │   default keyless lane (html: native, terms via mstrans:dictionary).
 ├─ BaiduEngine — Baidu Translate (html: none, finite language catalog).
 └─ (future) AzureEngine, TencentEngine — same protocol.
```

Routing sits above engines, and the pipeline sits above routing — the router
picks an engine and handles failure, the pipeline decides what to send it
(chunking, glossary narrowing, per-chunk context, response assembly):

- **Lanes**: config defines an ordered engine list per task type
  (`short_text` vs `chapter`). E.g. the default chapter lane is `bing` →
  `gemini-flash` → `gemini-flash-lite` → `gpt-oss-120b:nitro`, keyless Bing
  first so it always works.
- **Rate limiting**: per-*provider* client-side pacing (rpm/rps from config),
  shared by every engine on the account, so we never hammer a free tier into
  a ban.
- **Fallback**: on `quota` errors the whole provider is marked exhausted until
  its window resets and the next lane is tried; `transient` errors retry with
  backoff on the same engine; `fatal` skips to the next lane immediately. The
  retry counts and cooldowns come from the failure policy, which a provider or
  an individual engine may override (resolved engine > provider > global) —
  a slow local model wants fewer retries than a fast hosted one.
- **Concurrency**: per-*provider* max-concurrency (free tiers often allow 1),
  shared across the account's engines. A busy provider (all slots in use) is
  skipped for the next lane engine that can start now; the request waits only
  if every eligible engine is busy — priority ordering with load spilling
  down the lane, not a rejection.

## HTML handling

Chapter HTML from lncrawl is simple (mostly `<p>`, `<br>`, occasional
`<img>`, `<b>/<i>`). Strategy depends on engine capability:

1. **`html: prompt`** (LLM engines): send HTML directly with strict
   instructions — translate text content only, preserve all tags/attributes,
   never translate inside `<code>`/`translate="no"`. After the call,
   **validate**: parse both sides, compare tag sequence; on mismatch attempt
   auto-repair (re-wrap paragraphs) or retry once, else fall back to the
   segment pipeline. Emit a warning either way.
2. **`html: native`** (DeepL/Azure/Google): pass through with the provider's
   HTML flag.
3. **`html: none`** (Baidu, other seq2seq models): the service extracts
   text segments with BeautifulSoup, translates them (batched), and reinjects
   into the original tree. Loses cross-paragraph context — acceptable for
   fallback lanes only.

**Chunking**: if a chapter exceeds an engine's input budget, split on
block-element boundaries with a small overlap of preceding translated text as
context; reassemble in order. One chapter normally fits a single LLM call.

## Glossary & prompting (LLM engines)

- The system prompt establishes: professional literary translator for the
  given genre/direction, keep honorifics policy, preserve markup, output
  format.
- The glossary is injected as a term table with an instruction to use these
  translations verbatim. Large glossaries are filtered to terms actually
  present in the source text (simple substring scan) to save tokens.
- When `extract_terms` is on, the model is asked to return, alongside the
  translation, a JSON block of newly encountered proper nouns (people,
  places, techniques, organizations) with the translation it chose. Parsed
  leniently; extraction failure never fails the translation — it just returns
  empty `new_terms`.
- `previous_chapter_tail` (when provided) anchors tone/tense continuity.

## Configuration

A single YAML file (persisted in the container's data volume), managed
remotely via the config API / web UI — provider API keys are part of it,
though they are write-only through the API: responses redact stored secrets
to a placeholder, which writes may send back to mean "keep the stored
value".

A *provider* owns credentials + rate limits; an *engine* is one model on a
provider. The file is a sparse overlay on the built-in defaults, so usually you
just set a key:

```yaml
providers:
  - id: gemini # set a key to enable this provider's gemini-* engines
    settings:
      api_key: <token>

# engines/routing are optional here — the defaults (keyless bing, gemini,
# groq, an openrouter lane) already apply. Override only what you change:
routing:
  chapter: [bing, gemini-flash] # keyless Bing first, then keyed lanes
```

Fields specific to an engine kind live under `settings`; which ones exist is
declared by the kind's class and served at `GET /schema`.

Engines whose provider requires a key that is not set yet are auto-disabled
(visible in `/engines`). Free tiers churn, so adding/removing a lane is a
config edit, never a code change.

## Deployment shape

One container: the FastAPI service (this repo), a thin HTTP client with no
in-process ML stack. The keyless Bing lane means a single container can always
translate even with no API keys. Users who want an offline/local lane can run
any OpenAI-compatible server (llama.cpp, Ollama, Docker Model Runner) and point
the pre-wired `local-llm` provider at it.

## Non-goals (v1)

- No job queue, progress tracking, or novel storage (lncrawl's job).
- No streaming responses (batch pipeline doesn't need them; can add SSE later).
- No EN→X quality tuning beyond passing the target language through.
- No glossary persistence (pass-through only).

## Testing strategy

- Unit: HTML segment extraction/reinjection round-trips; tag-structure
  validation/repair; glossary filtering; router fallback on quota errors
  (fake engines).
- Integration (opt-in, needs keys): one short text + one small HTML snippet
  per configured engine, asserting tag preservation.
- Fixture chapters in ZH/JA/KO under `tests/fixtures/` taken from public
  domain / synthetic text.
