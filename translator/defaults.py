"""Built-in default configuration, used when no config file exists.

Covers the known free-tier providers; an engine only becomes available when
its provider's key env var is set, so exporting whichever keys you have is
the entire setup. Customize at runtime via the config API (the first write
creates the config file) or by providing a config.yml.

Free tiers churn — see docs/translation-engines.md for signup details and
config.example.yml for a commented version of this structure.
"""

from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "providers": [
        # z.ai — email signup; GLM flash is free with no token cap (~1 req/s).
        {
            "id": "zai",
            "kind": "openai",
            "base_url": "https://api.z.ai/api/paas/v4",
            "api_key_env": "ZAI_API_KEY",
            "rps": 1,
            "max_concurrency": 1,
        },
        # aistudio.google.com — Google account only; quotas volatile.
        {
            "id": "gemini",
            "kind": "openai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key_env": "GEMINI_API_KEY",
            "rpm": 10,
            "max_concurrency": 2,
        },
        # cloud.cerebras.ai — free tier, ~1M tokens/day, very fast.
        {
            "id": "cerebras",
            "kind": "openai",
            "base_url": "https://api.cerebras.ai/v1",
            "api_key_env": "CEREBRAS_API_KEY",
            "rpm": 5,
            "max_concurrency": 1,
        },
        # console.mistral.ai — Experiment plan; phone verification, no card.
        {
            "id": "mistral",
            "kind": "openai",
            "base_url": "https://api.mistral.ai/v1",
            "api_key_env": "MISTRAL_API_KEY",
            "rpm": 2,
            "max_concurrency": 1,
        },
        # console.groq.com — free, no card, strict token/day caps.
        {
            "id": "groq",
            "kind": "openai",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key_env": "GROQ_API_KEY",
            "rpm": 30,
            "max_concurrency": 1,
        },
        # openrouter.ai — 50 req/day free; model lineup churns monthly.
        {
            "id": "openrouter",
            "kind": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "rpm": 20,
            "max_concurrency": 1,
        },
        # deepl.com/pro-api — optional NMT fallback for short strings.
        {
            "id": "deepl",
            "kind": "deepl",
            "api_key_env": "DEEPL_API_KEY",
            "monthly_chars": 500_000,
        },
    ],
    "engines": [
        {
            "id": "zai-glm-flash",
            "provider": "zai",
            "model": "glm-4.7-flash",
            "max_input_tokens": 200_000,
        },
        {
            "id": "gemini-flash",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "max_input_tokens": 250_000,
        },
        {
            "id": "cerebras-glm",
            "provider": "cerebras",
            "model": "zai-glm-4.7",
            "max_input_tokens": 30_000,
        },
        {
            "id": "mistral-large",
            "provider": "mistral",
            "model": "mistral-large-latest",
            "max_input_tokens": 100_000,
        },
        {
            "id": "groq-oss",
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "max_input_tokens": 8_000,
        },
        {
            "id": "or-nemotron",
            "provider": "openrouter",
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "max_input_tokens": 100_000,
        },
        {"id": "deepl", "provider": "deepl"},
    ],
    # Priority order among whichever engines have keys set. DeepL is last
    # for chapters (no glossary support) but early for short strings.
    "routing": {
        "chapter": [
            "zai-glm-flash",
            "gemini-flash",
            "cerebras-glm",
            "mistral-large",
            "or-nemotron",
            "groq-oss",
            "deepl",
        ],
        "short_text": [
            "zai-glm-flash",
            "gemini-flash",
            "deepl",
            "cerebras-glm",
            "mistral-large",
            "or-nemotron",
            "groq-oss",
        ],
    },
}
