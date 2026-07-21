# Translation Engine Research

Research into zero-cost translation options for CJK→EN web-novel translation.
Compiled **2026-07-21** — free tiers change often (several major changes in the
last 8 months alone), so re-verify limits in the provider console at signup
time.

**Workload model used throughout:** one chapter ≈ 2,000 EN words ≈ ~6,000 CJK
source characters ≈ ~3,000 input tokens (chapter + prompt + glossary) and
~2,700 output tokens. A large novel ≈ 2,000 chapters.

## TL;DR — recommended engine lineup

The MTL/fan-translation community has largely moved from sentence-level NMT
(Google/DeepL/Papago) to LLMs for novel translation: LLMs handle implicit
subjects, honorifics, glossary enforcement, and cross-sentence context that
NMT structurally cannot. Quality ranking for literary CJK→EN:
**LLMs > Papago (KO)/Sugoi (JA) > Google ≈ DeepL > Azure > LibreTranslate
(unusable)**.

Recommended tiers, all switchable via config:

| Tier | Engine | Cost | Throughput | Notes |
|---|---|---|---|---|
| **Primary** | Z.AI **GLM-4.7-Flash** | Free, no token cap | ~2–5 days/novel (1 rps, latency-bound) | Chinese-native frontier model; arguably best free-forever pick for ZH→EN. 200K ctx. |
| **Quality pass** | **Gemini 3 Flash / 2.5 Flash** free tier | Free | 250–1,500 req/day/project (volatile) | Top quality among free options; quotas unstable since Dec 2025; free tier trains on data (except EU/UK/CH). |
| **Parallel lanes** | **Cerebras** (`zai-glm-4.7`, 1M tok/day) · **Mistral** (~1B tok/mo, mid CJK quality) | Free | ~175/day · ~2,800/day | Good backup/burst lanes behind the same OpenAI-compatible client. |
| **NMT fallback** | **DeepL API Free** | 500K chars/mo | ~83 chapters/mo | Best native HTML handling (`tag_handling=html`, tags unbilled) + free glossary for JA/KO/ZH→EN. Good for metadata/short texts. |
| **Local fallback** | **Qwen3.5-4B** Q4 (safe) or **Qwen3.5-9B** Q4 (quality, tight) via llama.cpp | Free (own CPU) | ~250/day · ~125/day on a 4 vCPU / 8 GB box | Fully private; no rate limits; slowest but viable for days-scale batch. |
| **Nearly-free escape hatch** | **DeepSeek** paid API | **~$2–3 per 2,000-ch novel** | Fast | Community-#1 ZH→EN quality (COMET ~0.90). Cheapest quality-per-dollar anywhere. |

Design implication: almost every engine above (Z.AI, Cerebras, Mistral,
OpenRouter, Groq, DeepSeek, ModelScope, llama.cpp server) speaks the
**OpenAI-compatible chat API** — one LLM engine class + per-provider config
presets covers them all. DeepL needs its own small client. That, plus a
provider-rotation/fallback layer, is the core of the engine design.

---

## 1. Free-tier hosted LLM APIs

| Provider | Best free model(s) | Binding limit | Chapters/day | 2,000-ch novel | Trains on data? |
|---|---|---|---|---|---|
| **Z.AI (Zhipu intl.)** | GLM-4.7-Flash, GLM-4.5-Flash | ~1 rps, concurrency 1 (no token cap) | ~500–2,000 | **~2–5 days** | Assume yes |
| **Google Gemini** | Gemini 3 Flash, 2.5 Flash/Lite (Pro removed ~Apr 2026) | 10 RPM; RPD 250–1,500, volatile | 250–1,500 (often less) | ~1.5–8 days optimistic | **Yes** (except EU/UK/CH) |
| **Mistral** (Experiment plan) | Mistral Large 3 / Medium | ~1B tok/mo; ~2 RPM (conflicting reports) | ~2,800 | **~1–2 days** | Yes by default, **opt-out in console** |
| **Cerebras** | zai-glm-4.7, gpt-oss-120b, gemma-4-31b | 1M tokens/day | ~175 | ~11–12 days | Unverified |
| **ModelScope (Alibaba)** | Qwen3/DeepSeek/GLM family | 2,000 req/day (~500/model) | up to ~2,000 | ~1–4 days | Unclear; needs Alibaba account + real-name verification |
| **Cloudflare Workers AI** | Qwen3-30B-A3B, GLM-4.7-Flash | 10,000 neurons/day | ~104 (Qwen3-30B) | ~19 days | Claims no training |
| **OpenRouter :free** | Nemotron-3, Gemma-4-31B (free lineup volatile; DeepSeek/Qwen/GLM purged Jun 2026) | 50 req/day (or **1,000/day after one-time $10 credit**) | 50 / 1,000 | 40 days / **~2 days** | Provider-dependent |
| **Groq** | gpt-oss-120b, llama-3.3-70b | 100–200K tokens/day | ~17–35 | 57–115 days | **No** (cleanest data policy) |
| **DashScope intl.** | qwen-max/plus/qwen3 | One-time ~1M+1M tokens/model, 90 days | one-time | ~330 ch/model, rotate models once | Claims no (unverified) |
| **DeepSeek** | V4 / V4 Flash | One-time 5M-token grant, then paid | — | **~$2.35 paid** for a full novel | — |
| **NVIDIA NIM** | 100+ models | One-time ≤5,000 request credits | one-time | not sustainable | Assume yes |
| **GitHub Models** | — | **Retired July 30, 2026** | — | — | — |

Notes:

- Gemini free-tier limits are no longer published per-model; real values show
  only in [AI Studio](https://aistudio.google.com/rate-limit) and were
  stealth-cut in Dec 2025. Treat as a quality lane, not a dependable primary.
- Groq is the only free tier with a clear no-training policy (+ ZDR option) —
  the privacy pick despite weak throughput.
- Sources: [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits),
  [Gemini terms](https://ai.google.dev/gemini-api/terms),
  [Z.AI pricing](https://docs.z.ai/guides/overview/pricing),
  [Cerebras limits](https://inference-docs.cerebras.ai/support/rate-limits),
  [Groq limits](https://console.groq.com/docs/rate-limits) /
  [data policy](https://console.groq.com/docs/your-data),
  [OpenRouter limits](https://openrouter.ai/docs/api-reference/limits),
  [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/),
  [Model Studio free quota](https://www.alibabacloud.com/help/en/model-studio/new-free-quota).

## 2. Dedicated MT APIs (sentence-level NMT)

Lower literary quality than LLMs, but official quotas, predictable behavior,
and (for some) native HTML handling. Best role: metadata/short texts, and bulk
fallback when LLM lanes are exhausted.

| Service | Free quota | Chapters/mo | HTML | Glossary | Catch |
|---|---|---|---|---|---|
| **DeepL API Free** | 500K chars/mo | ~83 | **Yes** (`tag_handling=html`, tags unbilled) | **Yes**, JA/KO/ZH→EN | Credit card required at signup |
| **Azure Translator F0** | 2M chars/mo | ~333 | Yes (`textType=html`) | Not on F0 practically | Card for Azure signup; 1 F0/subscription |
| **Google Cloud Translation** | 500K chars/mo ($10 credit) | ~83 | Yes | Yes (v3, via GCS) | Billing account required; overage auto-bills |
| **Tencent TMT** | **5M chars/mo** | ~833 | No (plain text) | No | Largest recurring quota; intl. signup OK (no CN phone) |
| **Amazon Translate** | Legacy accounts only post-Jul 2025 | — | No (real-time) | Yes | New accounts get one-time credits only |
| **Baidu Advanced** | 1M chars/mo | ~166 | No | Partial | **Requires Chinese phone + ID** |
| **Papago (NCP)** | None | 0 | Yes | No | Best-in-class KO quality but paid-only API |
| **Yandex** | None | 0 | — | — | Free API discontinued |
| **LibreTranslate** (self-host) | Unlimited | ∞ | Yes | No | **Unusable quality** for literary CJK→EN |
| Unofficial Google/Bing scrapers | "Unlimited" | — | No | No | ToS-violating, IP bans, breaks without notice — not for an unattended pipeline |

Stacking DeepL + Azure + Google + Tencent legally yields ~8M chars/mo ≈
~1,300 chapters/mo of NMT-grade output.

Sources: [DeepL plans](https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans) /
[HTML handling](https://developers.deepl.com/docs/xml-and-html-handling/html),
[Azure limits](https://learn.microsoft.com/en-us/azure/ai-services/translator/service-limits),
[Google pricing](https://cloud.google.com/translate/pricing),
[Tencent TMT](https://intl.cloud.tencent.com/products/tmt),
[LibreTranslate](https://github.com/LibreTranslate/LibreTranslate).

## 3. Local models (CPU-only, 4 vCPU / 8 GB RAM)

Realistic decode speed on a shared 4-vCPU box: ~4–6 tok/s for 7–9B Q4,
~8–12 tok/s for 4B Q4. RAM, not speed, is the binding constraint.

| Model | Q4 RAM | Fits 8 GB? | Chapters/day (24/7) | 2,000-ch novel | Verdict |
|---|---|---|---|---|---|
| **Qwen3.5-4B** | ~4–5.5 GB | Comfortable | ~250 | **~8 days** | **Default local pick.** Full instruction-following (HTML + glossary in one prompt), 256K ctx. MTP GGUFs give 1.4–2x CPU speedup. |
| **Qwen3.5-9B** | ~6.5 GB | Marginal (~1.5 GB headroom) | ~125 (MTP ~200) | ~10–16 days | Quality upgrade if the box has nothing else resident. |
| **Hunyuan-MT-7B** | ~4.5 GB | Yes | ~140 | ~14 days | WMT25 winner (30/31 pairs); best raw MT fidelity per parameter, but fixed-prompt — **no HTML/glossary instructions**; needs a markup-handling wrapper. Check license territory restrictions (EU exclusions). |
| **TranslateGemma-4B** | ~2.5 GB | Comfortable | ~250 | ~8 days | Strong tiny translator but ~2K-token segment-level input, no glossary/HTML. |
| **Tower-Plus-9B / 2B** | 5.8 / 1.7 GB | Tight / easy | ~115 / ~550 | ~17 / ~3.6 days | Covers ZH/JA/KO→EN, instruction-capable — but **CC-BY-NC-SA** (non-commercial). |
| vntl-llama3-8b-v2 | ~4.9 GB | Yes | ~125 | ~16 days | JA→EN VN-tuned niche pick (~32B-level for that niche). |
| Sugoi-14B-Ultra | ~9 GB | **No** | — | — | Best open JA→EN MTL; first grab after a RAM/GPU upgrade. |
| NLLB / MADLAD (CT2) | <3 GB | Trivial | 500+ | <4 days | Sentence-level seq2seq, poor literary quality, no instructions — not recommended. |
| Sakura/GalTransl models | — | — | — | — | JA→**ZH** only; wrong target language. |

Notes:

- Only full LLMs (Qwen, Gemma, Tower+) can do the whole pipeline in one
  prompt: glossary enforcement + HTML preservation + chapter-level coherence.
  Dedicated MT models (Hunyuan, TranslateGemma, NLLB) need the service to
  strip/chunk/reassemble markup around them.
- Serving: llama.cpp server directly (not Ollama multi-model keep-alive),
  4 threads, 8K context, one chapter at a time; q8_0 KV cache on the 9B.
- JA/KO→EN generally wants 14B+ for cloud-comparable quality; small local
  models are weakest there — prefer hosted lanes for JA/KO.
- Benchmark the actual box with `llama-bench` (Qwen3.5-4B/9B Q4) before
  committing; published numbers for this hardware class are extrapolations.
- Sources: [Qwen3.5 GGUF docs](https://unsloth.ai/docs/models/qwen3.5),
  [MTP guide](https://unsloth.ai/docs/models/mtp),
  [Hunyuan-MT-7B](https://huggingface.co/tencent/Hunyuan-MT-7B),
  [TranslateGemma](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/),
  [Tower-Plus-9B](https://huggingface.co/Unbabel/Tower-Plus-9B),
  [VNTL leaderboard](https://huggingface.co/datasets/lmg-anon/vntl-leaderboard),
  [CPU benchmark](https://markaicode.com/benchmarks/tool-cpu-benchmark/).

## 4. Paid escape hatches (last resort, kept open)

- **DeepSeek API**: ~$0.14–0.28/M tokens → a full 2,000-chapter novel for
  **~$2–3**, with community-#1 ZH→EN quality. The strongest argument that
  "zero cost" is worth relaxing.
- **OpenRouter one-time $10 credit**: permanently unlocks 1,000 free
  requests/day on `:free` models (~2 days/novel) without spending the credit.
- **Spot GPU batch**: RTX 4090 at ~$0.27–0.35/hr (Vast/TensorDock) translates
  a 2,000-chapter novel in ~50 GPU-hours ≈ **$15–20 one-off**, unlocking
  14B–27B models (Sugoi-14B, Qwen3.5-27B) at cloud-tier quality.
- **Dedicated GPU VPS**: ~$16–110/mo depending on card — only if translation
  becomes a continuous high-volume workload.

## 5. Data-privacy summary

Novel text is public content, so training-data exposure is low-stakes here,
but for the record: Groq (no training, ZDR) and Cloudflare (claims no
training) are cleanest; Google free tier trains (except EU/UK/CH); Mistral
trains by default (console opt-out); Chinese providers unverified — assume
yes. Local models are fully private.

## 6. Volatility warnings

- Google stealth-cut free RPD in Dec 2025 and removed Pro from the free tier
  ~Apr 2026; real limits visible only in the console.
- OpenRouter purged free DeepSeek/Qwen/GLM/Kimi endpoints in Jun 2026; free
  lineup churns monthly.
- GitHub Models retires entirely on 2026-07-30.
- Amazon's advertised 12-month Translate tier applies only to pre-Jul-2025
  accounts.

**Design consequence:** the service must treat every hosted engine as
ephemeral — provider config lives in config files (not code), engines report
quota exhaustion distinctly from errors, and the caller can rotate/fallback
across lanes.
