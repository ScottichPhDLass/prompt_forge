# prompt_forge

Transforms conceptual / narrative JSON prompt decks into production-ready
prompt pairs using a local LLM. Supports **Ollama** and **LM Studio** as
backends, switchable via config or CLI flag. LM Studio is the right choice
on AMD iGPUs (Radeon 780M etc.) where Ollama lacks Vulkan support.

Two diffusion targets are supported and selected with `--target`:

- `flux` *(default)* — long-form prose positive + comma-separated negative,
  tuned for T5-class text encoders used by **FLUX.1, FLUX.2, Qwen-Image,
  Z-Image** and similar. Output schema is unchanged from earlier versions:
  every prompt becomes a `[positive_str, negative_str]` pair.
- `sdxl` — CLIP-friendly comma-separated tag lists with explicit weights and
  `BREAK` chunking, tuned for **Stable Diffusion XL** and its derivatives
  (Illustrious, Pony, JuggernautXL, RealVisXL, etc.). Output is a structured
  object per prompt so the rendered string and individual tag lists / weights
  can both be inspected and tooled on. CLIP token budget is enforced at
  ≤225 tokens (3 × 75-token chunks).

Implements the workflow you specified:

1. **Per-prompt hybrid rewrite** — the model decides per prompt whether to
   rewrite from scratch or just normalize, so well-formed prompts are not
   needlessly mangled. The output positive always opens with
   `realistic photographic <shot type> of …` and the output negative is a
   comma-separated list with the canonical artifact / CG / illustration
   prohibitions.
2. **Boilerplate recompute** — after every prompt in a set is rewritten, a
   second pass extracts terms common to ≥ ~60% of prompts into new positive
   and negative boilerplate strings, then a third pass strips those terms
   from each individual prompt so the per-prompt strings stay focused.
3. **Validation + one-shot repair** — every produced pair is checked against
   the spec (opening template, shot type, lighting/texture cues, baseline
   negative vocabulary, no monochrome leak, no sentences in negatives). If
   the check fails, the model gets exactly one repair attempt before the
   pipeline accepts the result.
4. **Resumable** — every set has a JSON checkpoint file. Re-running the same
   command picks up exactly where it left off.

The deck/set/prompt **order, count, model_name, display_name, description,
set name, set abbreviation, and set description are preserved verbatim**.
Only `prompts` and (optionally) `boilerplate` inside the targeted set(s)
are modified.

## Requirements

- Python 3.11+
- One of the following local LLM servers running with a chat-capable model loaded:
  - **Ollama** at `http://127.0.0.1:11434` (default port). Use this on NVIDIA
    GPUs or supported hardware.
  - **LM Studio** at `http://127.0.0.1:1234` (default port) with the
    “OpenAI-compatible local server” toggle ON. Use this on AMD iGPUs
    (Radeon 780M etc.) via Vulkan, or on Apple Silicon.
- No Python dependencies beyond the stdlib. A per-project virtual environment
  is still recommended — see *First-time setup* below.

## Install / Run

### First-time setup (virtual environment)

The project has zero third-party Python dependencies, but running it inside a
per-project virtual environment is recommended so the `python` you launch is
always the one you tested against, regardless of what's on your global
`PATH`. After unzipping, create the venv **once**:

```bash
cd prompt_forge                  # the unzipped project root (contains README.md)
python3 -m venv venv             # creates ./venv/
```

This writes a self-contained interpreter under `./venv/`. You only do this
once per checkout. The `venv/` directory is local to the project and safe to
delete and recreate at any time.

From then on, **activate the venv at the start of every shell session** before
running anything in this project:

```bash
# macOS / Linux
cd prompt_forge
source ./venv/bin/activate       # prompt now shows (venv) ...

# Windows (PowerShell)
cd prompt_forge
.\venv\Scripts\Activate.ps1

# Windows (cmd.exe)
cd prompt_forge
venv\Scripts\activate.bat
```

When you're done, `deactivate` returns the shell to your normal Python.

> All `python -m prompt_forge ...` commands shown below assume the venv is
> already activated in your current shell. If you'd rather not activate, you
> can call the venv's interpreter directly: `./venv/bin/python -m prompt_forge
> --ui` (or `.\venv\Scripts\python.exe -m prompt_forge --ui` on Windows).

### Web UI (recommended for everyday use)

Launch a local browser-based control panel for picking files, tuning every CLI
parameter, listing/testing the LLM connection, and streaming live run logs:

```bash
cd prompt_forge
source ./venv/bin/activate             # see 'First-time setup' above
python -m prompt_forge --ui            # opens http://127.0.0.1:8765/
# or, equivalently:
python -m prompt_forge.ui --port 8765 --no-browser
```

- All CLI parameters are exposed (basics in the main panel, the rest under
  **Advanced**).
- **Target** toggles FLUX vs SDXL; the default output path updates live
  (`<input>.sdxl.json` for SDXL).
- **List models** / **Test connection** call the configured Ollama or LM Studio
  host directly so you can pick from a dropdown of installed models.
- **Run** spawns the same `python -m prompt_forge …` command shown in the
  *Equivalent CLI command* expander; output streams live with a progress bar
  driven by the existing `[i/N] done` log lines. **Cancel** sends SIGTERM, then
  SIGKILL after a 5-second grace period.
- All overrides are persisted to **`./config.json`** (project root) on Save and
  on every run, so settings survive between sessions. Delete `config.json` to
  go back to defaults.
- **Hide completed decks and sets** (Selection card) trims the Deck/Set
  dropdowns to entries that still need work. Completion is determined by the
  current checkpoint folder + target: if every prompt for a set has been
  rewritten and the checkpoint's target matches the active run target, that
  set is considered done. A deck is hidden only when *every* set in it is done.
- **📦 Build output from cache** (Selection card) writes the configured
  Output JSON immediately using whatever's already in the cache — no LLM
  calls. Useful for spot-testing a partially processed input without waiting
  for every set to finish. Sets that aren't in the cache (or are partial, or
  have a target mismatch) are left as the original source data, so the output
  is a valid "best so far" snapshot.
- Server binds to `127.0.0.1` by default (loopback only). To open the UI to
  other machines on your LAN, pass `--host` explicitly:

  ```bash
  # Listen on every interface so any machine on the LAN can reach it:
  python -m prompt_forge --ui --host 0.0.0.0 --no-browser

  # Or restrict to a specific NIC:
  python -m prompt_forge --ui --host 192.168.1.42 --no-browser
  ```

  Clients then point a browser at `http://<server-host>:8765/`. **There is no
  authentication** — anyone who can reach the bound address can drive the UI
  and trigger subprocesses on the server. Only enable LAN binding on a
  network you trust. Consider a host firewall or putting the server behind
  an authenticating reverse proxy if you need anything stronger.

### Command line

```bash
cd prompt_forge
source ./venv/bin/activate    # Windows: .\venv\Scripts\Activate.ps1

# 1) Inspect what would be processed (no LLM calls):
python -m prompt_forge \
    -i ../film_stock_prompt_v4.json -o /tmp/out.json \
    --deck "Photojournalism" --set "HardNoir" --dry-run -v

# 2) Process a single set (recommended for review):
python -m prompt_forge \
    -i ../film_stock_prompt_v4.json -o ../film_stock_prompt_v4.forged.json \
    --config config.example.toml \
    --deck "Photojournalism" --set "HardNoir" -v

# 3) Process the whole file:
python -m prompt_forge \
    -i ../film_stock_prompt_v4.json -o ../film_stock_prompt_v4.forged.json \
    --config config.example.toml --all -v
```

## Configuration

All defaults live in `config.example.toml`. Copy it and edit, or override
any field on the command line:

| TOML key                         | CLI flag                       |
|----------------------------------|--------------------------------|
| `llm.provider`                   | `--provider {auto,ollama,lmstudio}` |
| `llm.host`                       | `--host`                       |
| `llm.model`                      | `--model`                      |
| `llm.api_key` (LM Studio only)   | `--api-key`                    |
| `llm.timeout_s`                  | `--timeout`                    |
| `llm.temperature`                | `--temperature`                |
| `llm.num_predict`                | `--num-predict`                |
| `llm.concurrency`                | `--concurrency`                |
| `pipeline.target`                | `--target {flux,sdxl}`         |
| `pipeline.checkpoint_dir`        | `--checkpoint-dir`             |
| `pipeline.recompute_boilerplate` | `--no-recompute-boilerplate`   |
| `pipeline.validate`              | `--no-validate`                |

`provider = "auto"` probes Ollama first, then LM Studio, and uses whichever
responds. Set explicitly if you run both. The legacy `[ollama]` section is
still read for backward compatibility.

### LM Studio quick setup

1. In LM Studio, open the **Developer** (or **Local Server**) tab and toggle
   the OpenAI-compatible server ON. Default port is `1234`.
2. Load the model you want to use from **My Models**. Note its model id (e.g.
   `qwen3-vl-4b-instruct`).
3. Run `python tests/test_ollama_connection.py --provider lmstudio --model <id>`
   to verify connectivity.

The CLI requires either `--all`, or BOTH `--deck` and `--set`. `--deck` and
`--set` accept either the exact name or the abbreviation, and substring
matches are allowed.

## Targets

### FLUX target *(default)*

Every prompt becomes a `[positive_str, negative_str]` pair. The positive is
a single cinematic paragraph that always opens with
`realistic photographic <shot type> of …`. The negative is a comma-separated
phrase list. The output file replaces the input in-place schema-wise — only
`prompts` and `boilerplate` inside processed sets change.

```bash
python -m prompt_forge \
    -i ../film_stock_prompt_v4.json -o ../film_stock_prompt_v4.forged.json \
    --config config.example.toml --all -v
```

### SDXL target

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

`boilerplate` becomes `{"positive_tags": [...], "negative_tags": [...]}`. The
canonical rendered prompt strings are obtained at runtime by joining the
boilerplate tag list with the per-prompt tag list, applying weights as
`(tag:1.2)`, and inserting `BREAK` at each `breaks` index. The convenience
helpers `prompt_forge.render_sdxl_positive` and `render_sdxl_negative` do
this for you. Both A1111 and ComfyUI accept this syntax natively.

SDXL output is written to `<input_stem>.sdxl.json` next to the input by
default, so the original FLUX file is left untouched. Pass `--output` to
override.

```bash
# Defaults: writes film_stock_prompt_v4.sdxl.json next to the input
python -m prompt_forge \
    -i ../film_stock_prompt_v4.json --all --target sdxl \
    --config config.example.toml -v
```

SDXL prompts cap out at 225 CLIP tokens (3 × 75). The validator estimates
token count and triggers a repair pass on overruns, so an out-of-budget
rewrite gets one chance to compress before being accepted.

**Checkpoints are target-scoped.** A `.forge_cache` produced for FLUX cannot
be reused for SDXL — the pipeline will refuse to run rather than mix shapes.
Use separate `--checkpoint-dir` values (e.g. `.forge_cache_flux` and
`.forge_cache_sdxl`) when running both back-to-back.

## Output

The output JSON is structurally identical to the input, with two
modifications inside each processed set, and one new top-level field:

- `prompts` becomes an array of `[positive, negative]` string pairs (FLUX)
  or structured SDXL objects, depending on `--target`.
- `boilerplate` is replaced with freshly extracted positive/negative content
  if `recompute_boilerplate` is true.
- A top-level `target` field records which target produced the file.

Sets that are not selected for processing are passed through untouched.

## Resumability

Every set writes `<checkpoint_dir>/deckNN_setMM.json` after each completed
prompt. If the process is killed mid-run, restart with the same arguments
and rewriting continues from the last completed prompt. Delete the
checkpoint file to force a clean re-run for that set.

## Files

```
prompt_forge/
├── README.md
├── config.example.toml
├── config.json            # written by the web UI on Save / Run (gitignore-friendly)
├── venv/                  # local virtual environment, created by `python3 -m venv venv`
└── prompt_forge/
    ├── __init__.py
    ├── __main__.py        # `python -m prompt_forge` (CLI) and `--ui` shortcut
    ├── cli.py             # argparse, config merge, ping, dispatch
    ├── llm_client.py      # Ollama + LM Studio clients with JSON mode + retries
    ├── ollama_client.py   # backwards-compat shim for the old import path
    ├── pipeline.py        # 3-phase pipeline + checkpointing, FLUX/SDXL aware
    ├── templates.py       # FLUX and SDXL template banks + select_templates()
    ├── validator.py       # structural checks (FLUX) + tag/budget checks (SDXL)
    ├── ui_server.py       # local stdlib HTTP/SSE server for the web UI
    └── ui/
        ├── __init__.py    # `python -m prompt_forge.ui`
        ├── __main__.py
        └── index.html     # single-page control panel (vanilla JS, no build step)
```
