# AGENTS.md

Guidance for AI agents working in this repository.

## What this project is

A self-contained Docker service that translates entire lightnovels/webnovels.
It exposes a **stateless HTTP translation API** consumed by
[lightnovel-crawler](https://github.com/dipu-bd/lightnovel-crawler) (local
checkout: `~/projects/lncrawl`), which owns the novel database and orchestrates
the per-chapter translation loop itself.

The service translates:

- **Short texts** — novel title, author, synopsis, tags, volume/chapter titles.
- **Chapter bodies** — ~2000 words each, mostly HTML. Markup must be preserved;
  only human-readable text gets translated.

Primary direction: **Chinese / Korean / Japanese → English** (highest quality
bar). English → other languages must work but quality is best-effort.

## Key decisions (agreed with the owner)

1. **Cost model**: zero-cost. Free-tier hosted APIs (e.g. Gemini free tier,
   DeepL Free, Groq/OpenRouter free models) are acceptable, plus a local-model
   engine as fallback/alternative. Engines are switchable via config so the
   owner can trade quality vs. hardware cost.
2. **Service shape**: fully stateless translate API. No job queue, no novel
   storage, no progress tracking, no persistence here — lncrawl does that.
3. **Throughput**: batch-friendly. A full novel (thousands of chapters) taking
   days is acceptable; design around free-tier rate limits, not speed.
4. **Glossary**: pass-through, not persisted. Requests may carry a per-novel
   glossary (character names, places, terms) as context; the service injects
   it into prompts and returns the (possibly extended) glossary in the
   response. lncrawl owns and maintains the glossary between calls, keeping
   this service fully stateless.
5. **Deployment target**: a modest cloud VPS (few vCPUs, ~8 GB RAM, **no
   GPU**). Local models must run CPU-only within that budget; if quality
   demands more, the owner may upgrade hardware as a last resort — keep
   options open.

## Repo layout

- `translator/` — the FastAPI app: `api.py` (routes), `router.py` (lane
  routing, rate limiting, fallback), `engines/` (OpenAI-compat + DeepL),
  `prompts.py` (LLM prompts/parsing), `html_tools.py` (chunking, segment
  pipeline, tag validation), `detect.py` (language detection), `config.py`.
- `tests/` — pytest suite; `helpers.py` has `FakeEngine`; realistic chapter
  fixtures in `tests/fixtures/{zh,ja,ko}.html`.
- `docs/` — engine research, service design, deployment guide.
- `config.example.yml` — all known free engine lanes, ready to uncomment.

## Commands

Tasks are defined with poethepoet in `pyproject.toml` (`uv run poe <task>`):

- `uv run poe check` — ruff + mypy + pytest; run before declaring work done.
- `uv run poe dev` — dev server (auto-reload); `uv run poe start` —
  production-style uvicorn; `uv run poe docker` — build & start compose.
- `uv run poe live-test` — opt-in real-engine smoke test (needs `config.yml`
  with at least one key env set; costs a trivial amount of quota).

## Conventions

- Python ≥ 3.12, managed with **uv** (`uv sync`, `uv run …`).
- **FastAPI** for the HTTP layer (matches lncrawl's stack).
- Lint/format with **ruff** (`uv run ruff check .`, `uv run ruff format .`).
- Type-check before declaring work complete.
- Keep the image small: multi-stage Dockerfile, models mounted/downloaded at
  runtime, not baked into the image.

## Workflow rules

- **Never run `git commit` or `git push`.** The owner commits manually: stop
  after each logical unit of work and draft a commit message (no
  `Co-Authored-By` trailer).
- Confirm before large refactors, deletions, or anything hard to reverse.
- Ask before critical design decisions instead of guessing.

## Related repository

`~/projects/lncrawl` — the consumer of this service. Relevant models in
`lncrawl/core/models.py` (`Novel`, `Volume`, `Chapter`): chapters carry
`title` and HTML `body`; novels carry `title`, `author`, `synopsis`, `tags`,
`language`, volumes and chapters. lncrawl already has DB migrations for
storing translated titles/bodies on its side.
