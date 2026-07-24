"""Built-in default configuration, used when no config file exists.

Curated free-tier providers, pre-wired without credentials; each API engine
lights up once its ``api_key`` is set. Bing (keyless, HTML-native NMT) is the
default lane; the LLM lanes (glossary + context) are used when keyed. A
``config.yml`` is a sparse overlay merged onto these by
id (see ``config.py``), so changes here reach existing installs. Free tiers
churn (model ids especially) — verify in the provider console; signup details
in docs/translation-engines.md.

The lineup is deliberately small: only free lanes that are actually usable
without a paywall, a hard-to-get account, or a quota too small to matter.
Others (z.ai, Cerebras, ModelScope, SambaNova, Scaleway, DeepL, OpenRouter,
Mistral, DashScope, NVIDIA, Baidu) were dropped for one of those reasons; their
``kind`` handlers remain in the code, so any of them can be re-added via config.
"""

from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "providers": [
        # Microsoft Translator via Edge's keyless auth endpoint — no account,
        # HTML-native, strong quality, fast. The workhorse keyless lane.
        {
            "id": "bing",
            "kind": "bing",
            "requires_key": False,
            "rps": 3,
            "max_concurrency": 2,
        },
        # deepl.com/pro-api — NMT fallback for short strings; HTML-native.
        {
            "id": "deepl",
            "kind": "deepl",
            "monthly_chars": 500_000,
        },
        # Local OpenAI-compatible LLM server (Docker Model Runner, llama.cpp,
        # Ollama, LM Studio etc.)
        {
            "id": "local-llm",
            "kind": "openai",
            "base_url": "http://localhost:12434/engines/v1",
            "requires_key": False,
            "max_concurrency": 1,
        },
        # aistudio.google.com — free, Google account only; ~1,500 req/day.
        {
            "id": "gemini",
            "kind": "openai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "rpm": 10,
            "max_concurrency": 2,
        },
        # console.groq.com — free, no card, very fast; small token/day cap, so
        # it burns out quickly on long novels but is a good burst/short lane.
        {
            "id": "groq",
            "kind": "openai",
            "base_url": "https://api.groq.com/openai/v1",
            "rpm": 30,
            "max_concurrency": 1,
        },
        # openrouter.ai — 50 req/day free; model lineup churns monthly.
        {
            "id": "openrouter",
            "kind": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "rpm": 20,
            "max_concurrency": 1,
        },
        # cloud.sambanova.ai — free API key, no card; very fast RDU inference.
        # 50 req/day free, 1,000/day after a one-time $10 top-up.
        {
            "id": "sambanova",
            "kind": "openai",
            "base_url": "https://api.sambanova.ai/v1",
            "rpm": 10,
            "max_concurrency": 1,
        },
        # chutes.ai — no card; hosts open DeepSeek / Qwen / GLM weights, strong
        # on CJK. OpenAI-compatible; free lineup varies.
        {
            "id": "chutes",
            "kind": "openai",
            "base_url": "https://llm.chutes.ai/v1",
            "rpm": 30,
            "max_concurrency": 2,
        },
    ],
    "engines": [
        # "-latest" aliases track Google's current flash release, so they don't
        # 404 when a version is retired (2.5-flash already is).
        {
            "id": "gemini-flash",
            "provider": "gemini",
            "model": "gemini-flash-latest",
            "max_input_tokens": 250_000,
        },
        {
            "id": "gemini-flash-lite",
            "provider": "gemini",
            "model": "gemini-flash-lite-latest",
            "max_input_tokens": 250_000,
        },
        {
            "id": "groq-oss",
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "max_input_tokens": 8_000,
        },
        # OpenRouter gpt-oss-120b via the :nitro (highest-throughput) route;
        # needs an openrouter api key, so it's auto-disabled until one is set.
        {
            "id": "gpt-oss-120b:nitro",
            "provider": "openrouter",
            "model": "openai/gpt-oss-120b:nitro",
            "max_input_tokens": 8_000,
            "chunk_tokens": 2_000,
        },
        {
            "id": "bing",
            "provider": "bing",
        },
        # Disabled example: set `model` to one you've pulled, enable it, add it
        # to a routing lane. Budgets are sized small for quantized local models;
        # enable_thinking=false stops reasoning models burning the budget.
        {
            "id": "qwen3.5-4B",
            "provider": "local-llm",
            "model": "docker.io/ai/qwen3.5:4B-UD-Q4_K_XL",
            "enabled": False,
            "max_input_tokens": 8_000,
            "chunk_tokens": 2_000,
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                },
            },
        },
    ],
    # Priority order among whichever engines have keys set.
    "routing": {
        "chapter": [
            "bing",
            "gemini-flash",
            "gemini-flash-lite",
            "gpt-oss-120b:nitro",
        ],
        "short_text": [
            "bing",
            "groq-oss",
            "gemini-flash",
            "gemini-flash-lite",
            "gpt-oss-120b:nitro",
        ],
    },
}
