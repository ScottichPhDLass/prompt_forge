# prompt_forge

**v0.5.0** — Transform conceptual/narrative JSON prompt decks into production-ready
prompt pairs using a local LLM. Supports **Ollama**, **LM Studio**, **OpenAI-compatible**
backends, and a separate **stripper LLM** for the boilerplate-removal pass.

Two diffusion targets:

- **`flux`** *(default)* — long-form prose positive + comma-separated negative,
  tuned for T5-class text encoders (FLUX.1, FLUX.2, Qwen-Image, etc.)
- **`sdxl`** — CLIP-friendly comma-separated tag lists with explicit weights
  and `BREAK` chunking for SDXL and its derivatives (Illustrious, Pony,
  JuggernautXL, RealVisXL, Perfection, Realism Engine, etc.)

Four prompt **variants** (two per target) let you match the LLM's output style
to the checkpoint family — tag-based vs photographic for SDXL, prose vs hybrid
for FLUX.

---

## Features

- **Two-phase LLM pipeline** — rewrite → extract boilerplate → strip boilerplate
- **Separate stripper provider** — point a small/fast model at a different host
  for the strip phase (e.g. 4B on an eGPU while the main 27B on an iGPU does
  the heavy rewriting)
- **Four prompt variants** — `sdxl-tag`, `sdxl-photo`, `flux-prose`, `flux-hybrid`
  with archetype-specific system prompts
- **Dynamic extractor sample sizing** — measures the model's context window and
  fits the boilerplate-extraction sample within it automatically, avoiding
  `n_keep >= n_ctx` errors
- **Validation + one-shot repair** — every prompt is structurally validated;
  failures get exactly one LLM repair pass
- **Resumable** — JSON checkpoints per set. Kill and restart; it picks up where
  it left off
- **Web UI** — full control panel with live log streaming, model listing,
  connection testing, and cache-based partial builds
- **Systemd integration** — `deploy/prompt-forge-ui.service` for auto-start on
  server boot (tested on LXC/Linux)
- **Stdlib only** — zero third-party Python dependencies

---

## Quick start

```bash
python3 -m venv venv
source ./venv/bin/activate

# Process a single set with auto-detected provider
python -m prompt_forge \\
    -i input.json -o output.json \\
    --deck "Photojournalism" --set "HardNoir" -v

# Or launch the web UI
python -m prompt_forge --ui
```

---

## Web UI

```bash
python -m prompt_forge --ui               # opens http://127.0.0.1:8765/
python -m prompt_forge --ui --host 0.0.0.0 # LAN access (no auth — trust your network)
```

All CLI parameters are exposed in the browser panels:

| Card | What you can do |
|---|---|
| **Input/Output** | Pick files, choose target and variant |
| **Selection** | Browse input JSON structure, filter by deck/set, hide completed |
| **LLM provider** | Provider, host, model, API key, reasoning effort |
| **Stripper provider** | *(optional, collapsed by default)* Separate LLM for stripping |
| **Advanced** | Timeout, concurrency, temperature, num_predict, context_length, checkpoint dir, validate, recompute boilerplate |

Settings are persisted to `config.json` on every save and run.

---

## Variants

Variants map prompt archetypes to the LLM system prompt, steering output format
and vocabulary. Each variant implies its target.

| Variant | Target | Archetype | Best for |
|---|---|---|---|
| `sdxl-tag` | SDXL | Tag-based (booru-style) | Illustrious, Pony, CyberRealistic, danbooru-derived models |
| `sdxl-photo` | SDXL | Photographic (descriptive phrases) | Juggernaut, Perfection Cinematic, Realism Engine, EpicRealism |
| `flux-prose` | FLUX | Natural language prose | FLUX Dev, FLUX Schnell, Qwen-Image |
| `flux-hybrid` | FLUX | Tag + prose mix | FLUX + RealismLoRA |

```bash
python -m prompt_forge --variant sdxl-photo --deck "Photojournalism" --set "HardNoir" -v
```

When a variant is set, `--target` is derived automatically. Conflicting explicit
targets raise an error.

---

## Stripper provider

Boilerplate stripping is a simple string-subtraction task — well suited to a
smaller, faster model on different hardware. Point it anywhere:

```bash
python -m prompt_forge \\
    --provider lmstudio --host http://10.0.0.248:1234 --model huihui-qwen3.6-27b \\
    --stripper-provider lmstudio --stripper-host http://egpu:1234 --stripper-model gemma-4-e4b \\
    --deck "Photojournalism" --set "HardNoir" -v
```

When no stripper is configured, the main LLM is used for both rewrite and strip
— behaviour identical to v0.4.x. Unreachable stripper hosts fall back to the
main LLM with a warning.

---

## CLI reference

```
usage: python -m prompt_forge --input INPUT [options]

Required:
  --input / -i PATH       Input JSON file (decks / sets / prompts)

Selection (pick one pattern):
  --all                   Process every deck and set
  --deck DECK             Deck display name or model name (case-insensitive substring match)
  --set SET               Set name or abbreviation (requires --deck, case-insensitive)

Target:
  --target {flux,sdxl}    Diffusion target (default: flux)
  --variant VAR           Prompt archetype (implies target)

LLM provider:
  --provider {auto,ollama,lmstudio,openai,gemini,deepseek}
  --host URL              Server URL (http://...)
  --model NAME            Model ID as known to the provider
  --api-key KEY           For LM Studio / hosted providers
  --reasoning-effort {low,medium,high}
  --context-length N      Model context window in tokens (default: 8192)

Stripper provider (optional):
  --stripper-provider {auto,ollama,lmstudio}
  --stripper-host URL
  --stripper-model NAME
  --stripper-api-key KEY

Tuning:
  --timeout SEC           Per-LLM-call timeout (default: 240)
  --temperature FLOAT     (default: 0.4)
  --num-predict N         Max output tokens (default: 1200)
  --concurrency N         Parallel workers (default: 2)

Pipeline:
  --checkpoint-dir PATH   (default: .forge_cache)
  --no-recompute-boilerplate
  --no-validate

Misc:
  --dry-run               List targets and exit (no LLM calls)
  -v / -vv                Verbosity (info / debug)
```

---

## Config file

All defaults can be overridden via TOML. Example `config.toml`:

```toml
[llm]
provider = "lmstudio"
host = "http://10.0.0.248:1234"
model = "huihui-qwen3.6-27b"
context_length = 16384
timeout_s = 3600
temperature = 0.4
num_predict = 4096
concurrency = 2

[stripper]
provider = "lmstudio"
host = "http://egpu:1234"
model = "gemma-4-e4b"
timeout_s = 60
num_predict = 1024

[pipeline]
target = "sdxl"
variant = "sdxl-tag"
checkpoint_dir = ".forge_cache_tag"
```

---

## Targets in detail

### FLUX (default)

Every prompt becomes a `[positive_str, negative_str]` pair. The positive is a
single cinematic paragraph opening with `realistic photographic <shot type> of …`.
The negative is a comma-separated phrase list.

```bash
python -m prompt_forge -i input.json -o output.json --all -v
```

### SDXL

Every prompt becomes a structured object:

```json
{
  "decision": "rewrite",
  "shot_type": "medium shot",
  "positive_tags": ["realistic photograph", "medium shot", "a detective", "..."],
  "negative_tags": ["3d render", "illustration", "..."],
  "weights": {"chiaroscuro lighting": 1.2},
  "breaks": [12, 24]
}
```

Output is written to `<input_stem>.sdxl.json` by default. Boilerplate becomes
`{"positive_tags": [...], "negative_tags": [...]}`.

The validator enforces ≤ 225 CLIP tokens (3 × 75-token chunks). Auto-BREAK and
auto-weight passes insert missing BREAKs at 75-token boundaries and fill default
1.0 weights for unweighted tags.

```bash
python -m prompt_forge -i input.json --all --target sdxl --variant sdxl-photo -v
```

---

## Pipeline phases

For each (deck, set) pair:

1. **Phase 1 — Rewrite** — Every prompt is sent to the LLM with the target- and
   variant-specific system prompt. Resumable via checkpoint.
2. **Phase 2 — Boilerplate extract** — An evenly-spaced sample of rewritten
   prompts is sent to the LLM to extract set-wide common terms. Sample size is
   calculated dynamically from the model's `context_length` to avoid overflow.
3. **Phase 3 — Boilerplate strip** — Every prompt is sent to the *stripper*
   LLM (or the main LLM if no separate stripper is configured) to remove
   boilerplate terms, leaving only per-scene unique content.

All phases are logged at INFO level with progress indicators.

---

## Deployment

A systemd service is provided in the repository for auto-start on boot:

```bash
cp deploy/prompt-forge-ui.service /etc/systemd/system/
systemctl enable --now prompt-forge-ui.service
journalctl -u prompt-forge-ui.service -f
```

The service uses the project's own venv and binds to `0.0.0.0:8765`.

---

## File structure

```
prompt_forge/
├── README.md
├── config.example.toml
├── config.json              # written by the web UI (gitignore-friendly)
├── deploy/
│   └── prompt-forge-ui.service
├── venv/                    # created by `python3 -m venv venv`
└── prompt_forge/
    ├── __init__.py           # version, public API exports
    ├── __main__.py           # `python -m prompt_forge` entry point
    ├── cli.py                # argparse, config merge, dispatch
    ├── llm_client.py         # Ollama / LM Studio / OpenAI clients
    ├── ollama_client.py      # backwards-compat shim
    ├── pipeline.py           # 3-phase pipeline + checkpointing
    ├── templates.py          # template banks + variant definitions
    ├── validator.py          # structural / tag / budget validation
    ├── ui_server.py          # stdlib HTTP + SSE server
    └── ui/
        ├── __init__.py
        ├── __main__.py
        └── index.html        # single-page UI (vanilla JS)
```
