# Service Design

A stateless HTTP translation service for web novels, consumed by lncrawl
(which owns novel storage, orchestration, and the glossary between calls).

## Goals recap

- Translate short texts (titles, author, tags, synopsis) and HTML chapter
  bodies (~2,000 words), best quality for ZH/JA/KO→EN.
- Zero cost by default: free hosted lanes + local model, switchable by config.
- Fully stateless: glossary arrives in the request, returns (extended) in the
  response.
- Batch-friendly: built around free-tier rate limits, not speed.

## API surface

All endpoints are synchronous JSON over HTTP. Chapter translation can take
seconds (hosted LLM) to ~10 minutes (local CPU model) — callers must use long
client timeouts (lncrawl calls server-to-server, typically on the same host).
Optional bearer-token auth via `AUTH_TOKEN` env var (unset = open, for
localhost/private-network deployments).

### `GET /health`

Liveness + readiness (at least one engine configured and not quota-dead).

### `GET /engines`

Lists configured engines with capabilities and live status:

```json
{
  "engines": [
    {
      "id": "zai-glm-flash",
      "kind": "openai",
      "model": "glm-4.7-flash",
      "capabilities": {"html": "prompt", "glossary": true, "max_input_tokens": 200000},
      "status": "ok",            // ok | throttled | quota_exhausted | error | disabled
      "quota_resets_at": null
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

- `422` invalid request; `401` bad token; `502` engine failure after retries;
  `503` + `Retry-After` when all eligible lanes are quota-exhausted or
  throttled. Quota exhaustion is a first-class signal, not a generic error —
  lncrawl schedules around it.

## Language detection

Used by `/detect` and by the translate endpoints when `source_lang` is
omitted (the result is echoed back as `detected_source_lang`). Two layers:

1. **Script heuristics** — Unicode-range analysis separates hangul (ko),
   kana (ja), and hanzi-only text cheaply and near-perfectly for KO/JA;
   hanzi-only text is ambiguous between zh and ja.
2. **Statistical detector** — a small local library (e.g. `lingua-py` in
   low-accuracy mode or fastText `lid.176`) resolves ambiguous cases and
   covers non-CJK languages.

No network call, no engine quota. HTML input is text-extracted first.

## Engine abstraction

```
Engine (protocol)
 ├─ id, kind, capabilities: {html: native|prompt|none, glossary: bool,
 │   max_input_tokens, languages}
 ├─ async translate(segments, src, tgt, glossary, context) -> segments
 ├─ async translate_html(html, ...) -> (html, new_terms)   # only if html != none
 └─ classify_error(exc) -> transient | quota | fatal

Implementations
 ├─ OpenAICompatEngine — covers Z.AI, Cerebras, Mistral, Groq, OpenRouter,
 │   DeepSeek, ModelScope, Gemini (via its OpenAI-compat endpoint), and any
 │   local OpenAI-compatible server. One class, config-only differences.
 ├─ DeepLEngine — native HTML mode + native glossaries.
 ├─ NllbEngine — Meta's NLLB-200 in-process via CTranslate2; keyless
 │   last-resort lane (html: none, no glossary).
 └─ (future) AzureEngine, TencentEngine — same protocol.
```

Routing sits above engines:

- **Lanes**: config defines an ordered engine list per task type
  (`short_text` vs `chapter`). E.g. chapters try `zai-glm-flash` →
  `cerebras-glm` → `mistral-large` → `nllb`; short texts may prefer
  `deepl` first.
- **Rate limiting**: per-engine client-side token bucket (rpm/rps/tpd from
  config) so we never hammer a free tier into a ban.
- **Fallback**: on `quota` errors the engine is marked exhausted until its
  window resets and the next lane is tried; `transient` errors retry with
  backoff on the same engine; `fatal` skips to next lane immediately.
- **Concurrency**: per-engine max-concurrency (free tiers often allow 1).

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
3. **`html: none`** (Tencent, NLLB, other seq2seq models): the service extracts
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
remotely via the config API / web UI — provider API keys are part of it:

```yaml
engines:
  - id: zai-glm-flash
    kind: openai
    base_url: https://api.z.ai/api/paas/v4
    api_key: <token>
    model: glm-4.7-flash
    rps: 1
    max_concurrency: 1
    max_input_tokens: 200000
  - id: deepl
    kind: deepl
    api_key: <token>
    monthly_chars: 500000
  - id: nllb
    kind: nllb
    model: OpenNMT/nllb-200-distilled-1.3B-ct2-int8

routing:
  chapter: [zai-glm-flash, nllb]
  short_text: [zai-glm-flash, deepl, nllb]
```

Engines whose provider requires a key that is not set yet are auto-disabled
(visible in `/engines`). Free tiers churn, so adding/removing a lane is a
config edit, never a code change.

## Deployment shape

One container: the FastAPI service (this repo). The local NLLB fallback
runs in-process via CTranslate2 (CPU-only, no GPU stack), with the model
downloaded to the data volume on first use — so a single container is
always able to translate, even with no API keys. Users who want an
instruction-following local LLM lane can run any OpenAI-compatible server
(llama.cpp, Ollama) and add it as a `kind: openai` provider.

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
