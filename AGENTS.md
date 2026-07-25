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

The package is layered; imports only ever point _down_ this list, and only the
top level is public API.

- `translator/` — the public surface: `__init__.py` (lazy exports —
  `TranslatorService`, `create_app`, `detect_*`, the error taxonomy),
  `schemas.py` (the translation contract, shared by both front ends),
  `errors.py`, `service.py` (embedded sync facade over the core),
  `main.py` (`uvicorn translator.main:app`).
- `translator/server/` — the HTTP front end: `app.py` (factory), `routes/`
  (one module per resource), `deps.py`, `dto.py` (HTTP-only shapes),
  `editing.py` (config mutations), `secrets.py`, `middleware.py`,
  `handlers.py`, `static/` (dashboard SPA).
- `translator/core/` — transport-agnostic: `router.py` (lane selection,
  retries, fallback), `pipeline.py` (the workflow around an engine call —
  chunking, glossary, context, response assembly), `limits.py` (provider and
  engine health/throughput), `store.py` (live config + router).
- `translator/engines/` — one class per `kind`, all reached through
  `registry.py`; `base.py` is the protocol, `http.py` the shared client and
  error mapping, `prompts.py` the LLM prompts. Provider-specific language
  codes live with the engine that speaks them.
- `translator/text/` — dependency-light helpers: `html.py`, `languages.py`,
  `detect.py`, `glossary.py`. Nothing here knows about engines or HTTP.
- `translator/config/` — `models.py`, `defaults.py` (built-in free lanes),
  `overlay.py` (the sparse merge/diff), `io.py`. The optional `config.yml` is
  a sparse _overlay_ on the defaults, merged by id on load; see the deployment
  guide's "sparse overlay" section.
- `tests/` — pytest suite; `helpers.py` has `FakeEngine`; realistic chapter
  fixtures in `tests/fixtures/{zh,ja,ko}.html`.
- `docs/` — engine research, service design, deployment guide.

Adding an engine kind is one class in `translator/engines/` plus its entry in
`registry.py` and the `EngineKind` literal — the registry asserts the two
agree. Everything else (capabilities, credentials, language coverage) is
declared on the class and read from there by both the router and the API.

## Commands

Tasks are defined with poethepoet in `pyproject.toml` (`uv run poe <task>`):

- `uv run poe check` — ruff + mypy + pytest; run before declaring work done.
- `uv run poe dev` — dev server (auto-reload); `uv run poe start` —
  production-style uvicorn; `uv run poe docker` — build & start compose.
- `uv run poe live-test` — opt-in real-engine smoke test (needs `config.yml`
  with at least one key env set; costs a trivial amount of quota).
- CI (`.github/workflows/ci.yml`) runs `lint-check` (no auto-fix),
  `typecheck`, `test`, and a Docker build on pushes to main and PRs.
- Publish (`.github/workflows/publish.yml`) pushes multi-arch images to
  `ghcr.io/lncrawl/translator` on main pushes and `v*` tags.

## Conventions

- Python ≥ 3.12, managed with **uv** (`uv sync`, `uv run …`).
- **FastAPI** for the HTTP layer (matches lncrawl's stack).
- Lint/format with **ruff** (`uv run ruff check .`, `uv run ruff format .`).
- Type-check before declaring work complete.
- **No useless code comments.** Comment only non-obvious constraints or
  gotchas the code cannot express, one line max. Never narrate what the code
  does, restate names, or explain a change to the reviewer.
- Keep the image small: multi-stage Dockerfile, models mounted/downloaded at
  runtime, not baked into the image.

## Workflow rules

- **Never run `git commit` or `git push`.** The owner commits manually: stop
  after each logical unit of work and draft a commit message (no
  `Co-Authored-By` trailer).
- Confirm before large refactors, deletions, or anything hard to reverse.
- Ask before critical design decisions instead of guessing.

## Releasing

Releases are automated: bump -> tag -> GitHub Release (artifacts + changelog
notes) -> PyPI publish; the same tag also builds versioned Docker images.
Add a `## [x.y.z] - YYYY-MM-DD` section to `CHANGELOG.md` (its top entry is
the version of record), push to main, then run the **Bump Version** workflow —
it sets the version in `pyproject.toml`, commits, tags `vx.y.z`, and triggers
the release pipeline. Pushing a `v*` tag by hand triggers the same release.

## Related repository

`~/projects/lncrawl` — the consumer of this service. Relevant models in
`lncrawl/core/models.py` (`Novel`, `Volume`, `Chapter`): chapters carry
`title` and HTML `body`; novels carry `title`, `author`, `synopsis`, `tags`,
`language`, volumes and chapters. lncrawl already has DB migrations for
storing translated titles/bodies on its side.
