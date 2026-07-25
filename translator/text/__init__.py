"""Text processing shared by every engine and by the translation pipeline.

Dependency-light and side-effect free — nothing here knows about HTTP, config,
or a running engine:

- :mod:`~translator.text.languages` — BCP 47 tags: validation and canonical forms.
- :mod:`~translator.text.detect` — local language detection.
- :mod:`~translator.text.html` — token estimation, chunking, segments, validation.
- :mod:`~translator.text.glossary` — term filtering and placeholder enforcement.
"""
