"""Command-line entry point.

Examples
--------
# Auto-detect provider (Ollama if running, otherwise LM Studio), default FLUX target
python -m prompt_forge --input in.json --output out.json --all

# SDXL target (writes <input_stem>.sdxl.json next to the input by default,
# or override with --sdxl-output / --output)
python -m prompt_forge --input film_stock_prompt_v4.json --all --target sdxl

# Force LM Studio
python -m prompt_forge --input in.json --output out.json --all \
    --provider lmstudio --host http://127.0.0.1:1234 \
    --model qwen3-vl-4b-instruct

# Force Ollama
python -m prompt_forge --input in.json --output out.json --all \
    --provider ollama --host http://127.0.0.1:11434 \
    --model qwen2.5:32b-instruct

# One set at a time
python -m prompt_forge -i in.json -o out.json \
    --deck "Photojournalism" --set "HardNoir"
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# tomllib is stdlib in Python 3.11+
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore

from .llm_client import LLMConfig, LLMError, make_client
from .pipeline import Pipeline, PipelineConfig, RunSelection


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prompt_forge",
        description=(
            "Transform conceptual JSON prompt decks into production-ready "
            "[pos, neg] pairs via a local LLM (Ollama or LM Studio)."
        ),
    )
    p.add_argument("--input", "-i", required=True, help="Path to input JSON file (decks/sets/prompts).")
    p.add_argument(
        "--output", "-o", default=None,
        help=(
            "Path to write the transformed JSON. Optional; if omitted, output "
            "goes to '<input_stem>.<target>.json' next to the input file "
            "('<stem>.flux.json' for --target flux, '<stem>.sdxl.json' for sdxl)."
        ),
    )
    p.add_argument(
        "--target",
        choices=["flux", "sdxl"],
        default=None,
        help=(
            "Diffusion model family the prompts target. 'flux' (default) emits "
            "long-form prose for FLUX/Qwen/Z-Image-class T5 text encoders. 'sdxl' "
            "emits CLIP-friendly tag objects with weights and BREAK chunking for "
            "Stable Diffusion XL and its derivatives."
        ),
    )
    p.add_argument("--config", "-c", default=None, help="Path to a TOML config file (see config.example.toml).")

    # Selection
    p.add_argument("--deck", default=None, help="Deck display_name or model_name (case-insensitive, substring ok).")
    p.add_argument("--set", dest="set_name", default=None, help="Set name or abbreviation to process.")
    p.add_argument("--all", dest="process_all", action="store_true", help="Process every deck and set in the file.")

    # Provider selection
    p.add_argument(
        "--provider",
        choices=["auto", "ollama", "lmstudio"],
        default=None,
        help="LLM backend. 'auto' probes Ollama then LM Studio.",
    )
    p.add_argument("--host", default=None, help="LLM server URL (default depends on provider).")
    p.add_argument("--model", default=None, help="Model name as known to the provider.")
    p.add_argument("--api-key", default=None, help="API key (LM Studio only; any string works).")
    p.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default=None,
        help="Reasoning-model budget knob (LM Studio + reasoning models). "
             "Use 'low' for batch-rewrite work to keep visible content from "
             "being starved by hidden chain-of-thought.",
    )
    p.add_argument("--timeout", type=int, default=None, help="Per-call timeout in seconds.")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--num-predict", type=int, default=None, dest="num_predict",
                   help="Max output tokens (Ollama num_predict / LM Studio max_tokens).")
    p.add_argument("--concurrency", type=int, default=None, help="Parallel rewrite workers.")

    # Pipeline overrides
    p.add_argument("--checkpoint-dir", default=None)
    p.add_argument("--no-recompute-boilerplate", dest="recompute_boilerplate", action="store_false", default=None)
    p.add_argument("--no-validate", dest="validate", action="store_false", default=None)

    p.add_argument("--dry-run", action="store_true", help="List the deck/set targets that would be processed and exit.")
    p.add_argument("--verbose", "-v", action="count", default=0, help="-v info, -vv debug.")
    return p


def _load_toml(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _merge_config(toml_cfg: dict, args: argparse.Namespace) -> tuple[LLMConfig, PipelineConfig]:
    # The new section name is [llm]; we fall back to [ollama] for backward
    # compatibility with older configs.
    llm_cfg = toml_cfg.get("llm") or toml_cfg.get("ollama") or {}
    pipe = toml_cfg.get("pipeline", {})

    lcfg = LLMConfig(
        provider=args.provider or llm_cfg.get("provider", "auto"),
        # If host is empty and provider isn't set, make_client() will fill in
        # the right default based on the provider it picks.
        host=args.host or llm_cfg.get("host", ""),
        model=args.model or llm_cfg.get("model", ""),
        timeout_s=args.timeout or llm_cfg.get("timeout_s", 240),
        temperature=args.temperature if args.temperature is not None else llm_cfg.get("temperature", 0.4),
        top_p=llm_cfg.get("top_p", 0.9),
        num_predict=args.num_predict or llm_cfg.get("num_predict", 1200),
        max_retries=llm_cfg.get("max_retries", 3),
        api_key=args.api_key or llm_cfg.get("api_key", "lm-studio"),
        reasoning_effort=args.reasoning_effort or llm_cfg.get("reasoning_effort", ""),
    )
    target = args.target or pipe.get("target") or llm_cfg.get("target") or "flux"
    if target not in ("flux", "sdxl"):
        raise ValueError(f"Invalid target {target!r}; expected 'flux' or 'sdxl'.")
    pcfg = PipelineConfig(
        checkpoint_dir=args.checkpoint_dir or pipe.get("checkpoint_dir", ".forge_cache"),
        recompute_boilerplate=(
            pipe.get("recompute_boilerplate", True)
            if args.recompute_boilerplate is None
            else args.recompute_boilerplate
        ),
        validate=(
            pipe.get("validate", True) if args.validate is None else args.validate
        ),
        opening_template=pipe.get("opening_template", "realistic photographic {shot_type} of"),
        force_full_color=pipe.get("force_full_color", True),
        concurrency=args.concurrency or llm_cfg.get("concurrency", 2),
        target=target,
    )
    return lcfg, pcfg


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _setup_logging(args.verbose)

    if not args.process_all and not args.deck and not args.set_name:
        print(
            "error: specify --all, or --deck (with optional --set), or both "
            "--deck and --set.",
            file=sys.stderr,
        )
        return 2
    if not args.process_all and args.set_name and not args.deck:
        print("error: --set requires --deck.", file=sys.stderr)
        return 2

    toml_cfg = _load_toml(args.config)
    lcfg, pcfg = _merge_config(toml_cfg, args)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"error: input file not found: {in_path}", file=sys.stderr)
        return 2
    data = json.loads(in_path.read_text("utf-8"))

    # Resolve output path. Default for both targets is
    # '<input_stem>.<target>.json' next to the input, so the source file is
    # always left untouched unless the user explicitly overwrites it.
    if args.output:
        out_path = Path(args.output)
    elif args.dry_run:
        out_path = None  # dry-run never writes
    else:
        out_path = in_path.with_name(f"{in_path.stem}.{pcfg.target}.json")

    selection = RunSelection(
        deck=args.deck,
        set_name=args.set_name,
        process_all=args.process_all,
    )

    if args.dry_run:
        # Skip the LLM ping in dry-run; just enumerate matching targets.
        from .pipeline import Pipeline as _P
        # Build a stub-free pipeline with a no-op client placeholder.
        # We only call _iter_targets here, which doesn't touch the client.
        from .llm_client import OllamaClient
        pipeline = _P(OllamaClient(lcfg), pcfg)
        for di, si in pipeline._iter_targets(data.get("decks", []), selection):  # noqa: SLF001
            d = data["decks"][di]
            s = d["sets"][si]
            print(
                f"deck[{di}] {d.get('display_name') or d.get('model_name')} "
                f":: set[{si}] {s.get('name') or s.get('abbr')} "
                f"({len(s.get('prompts', []))} prompts)"
            )
        return 0

    try:
        client = make_client(lcfg)
    except Exception as e:
        print(f"error: failed to initialize LLM provider: {e}", file=sys.stderr)
        return 3

    try:
        if not client.ping():
            print(
                f"error: cannot reach {lcfg.provider} at {lcfg.host}. "
                f"Is the server running and is the model '{lcfg.model}' loaded?",
                file=sys.stderr,
            )
            return 3
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    print(
        f"Using provider={lcfg.provider}, host={lcfg.host}, model={lcfg.model}, target={pcfg.target}",
        file=sys.stderr,
    )

    pipeline = Pipeline(client, pcfg)
    out = pipeline.run(data, selection)
    # Record the target at top level so downstream consumers can branch on it.
    out["target"] = pcfg.target

    assert out_path is not None  # dry-run path returns earlier
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
