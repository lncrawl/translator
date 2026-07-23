"""Built-in default configuration, used when no config file exists.

Covers the known free-tier providers, pre-wired without credentials: an
API engine becomes available once its provider's ``api_key`` is set via
the web UI at / or the config API (the first write creates the config
file). A local NLLB model (no key needed) is the last-resort fallback,
so the service works out of the box.

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
            "rps": 1,
            "max_concurrency": 1,
        },
        # aistudio.google.com — Google account only; quotas volatile.
        {
            "id": "gemini",
            "kind": "openai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "rpm": 10,
            "max_concurrency": 2,
        },
        # cloud.cerebras.ai — free tier, ~1M tokens/day, very fast.
        {
            "id": "cerebras",
            "kind": "openai",
            "base_url": "https://api.cerebras.ai/v1",
            "rpm": 5,
            "max_concurrency": 1,
        },
        # console.mistral.ai — Experiment plan; phone verification, no card.
        {
            "id": "mistral",
            "kind": "openai",
            "base_url": "https://api.mistral.ai/v1",
            "rpm": 2,
            "max_concurrency": 1,
        },
        # console.groq.com — free, no card, strict token/day caps.
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
        # deepl.com/pro-api — optional NMT fallback for short strings.
        {
            "id": "deepl",
            "kind": "deepl",
            "monthly_chars": 500_000,
        },
        # Microsoft Translator via Edge's keyless auth endpoint — no account,
        # HTML-native, strong quality. Best-effort (unofficial) fallback lane.
        {
            "id": "bing",
            "kind": "bing",
            "requires_key": False,
            "rps": 3,
            "max_concurrency": 2,
        },
        # fanyi-api.baidu.com — free tier, strong on CJK. api_key is the pair
        # 'app_id:secret_key'; the standard free tier allows ~1 request/second.
        {
            "id": "baidu",
            "kind": "baidu",
            "rps": 1,
            "max_concurrency": 1,
        },
        # Built-in local NLLB (CTranslate2, CPU) — needs no key, so the
        # service always has a working lane even with zero providers set up.
        {
            "id": "local-nllb",
            "kind": "nllb",
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
        {"id": "bing", "provider": "bing"},
        {"id": "baidu", "provider": "baidu"},
        # Meta's NLLB-200 (distilled 1.3B, int8) running in-process.
        # ~1.4 GB download from Hugging Face on first use, then cached.
        {
            "id": "nllb",
            "provider": "local-nllb",
            "model": "OpenNMT/nllb-200-distilled-1.3B-ct2-int8",
        },
    ],
    # Priority order among whichever engines have keys set. LLM lanes first
    # (glossary + context). Then the keyless NMT lanes: DeepL, then Bing
    # (keyless, HTML-native), then Baidu (CJK, needs a key); local NLLB is the
    # final offline resort. Reorder freely in the dashboard.
    "routing": {
        "chapter": [
            "zai-glm-flash",
            "gemini-flash",
            "cerebras-glm",
            "mistral-large",
            "or-nemotron",
            "groq-oss",
            "deepl",
            "bing",
            "baidu",
            "nllb",
        ],
        "short_text": [
            "zai-glm-flash",
            "gemini-flash",
            "deepl",
            "cerebras-glm",
            "mistral-large",
            "or-nemotron",
            "groq-oss",
            "bing",
            "baidu",
            "nllb",
        ],
    },
}
