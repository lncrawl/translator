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

## Status

Early development. See [AGENTS.md](AGENTS.md) for project decisions and
conventions.
