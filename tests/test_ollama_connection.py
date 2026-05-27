"""Live connectivity test for the LLM provider defined in a TOML config.

Reads ``[llm]`` (or legacy ``[ollama]``) settings from a config file (default:
../config.example.toml relative to this script), pings the server, lists
available models, verifies the configured model is loaded, and sends a small
chat request to confirm end-to-end operation including JSON mode.

Works with both **Ollama** and **LM Studio** — the provider is selected via
the config or ``--provider``. ``--provider auto`` probes both.

Usage
-----
    python tests/test_ollama_connection.py
    python tests/test_ollama_connection.py --config /path/to/my.toml
    python tests/test_ollama_connection.py --provider lmstudio \
                                           --host http://127.0.0.1:1234 \
                                           --model qwen3-vl-4b-instruct

Exit codes
----------
    0  all checks passed
    1  unexpected error
    2  bad arguments / config not found
    3  server unreachable
    4  configured model not loaded on the server
    5  chat request failed or returned malformed JSON
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
sys.path.insert(0, str(PKG_ROOT))

from prompt_forge.llm_client import (  # noqa: E402
    LLMConfig,
    LLMError,
    LMStudioClient,
    OllamaClient,
    make_client,
)


# ---------------------------------------------------------------------------
# Pretty output helpers
# ---------------------------------------------------------------------------

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET}   {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET} {msg}")


def _info(msg: str) -> None:
    print(f"  {DIM}..{RESET}   {msg}")


def _section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config(path: Path) -> dict:
    if not path.exists():
        print(f"error: config file not found: {path}", file=sys.stderr)
        sys.exit(2)
    with open(path, "rb") as f:
        return tomllib.load(f)


def _build_llm_config(toml_cfg: dict, args: argparse.Namespace) -> LLMConfig:
    section = toml_cfg.get("llm") or toml_cfg.get("ollama") or {}
    return LLMConfig(
        provider=args.provider or section.get("provider", "auto"),
        host=args.host or section.get("host", ""),
        model=args.model or section.get("model", ""),
        timeout_s=args.timeout or section.get("timeout_s", 120),
        temperature=section.get("temperature", 0.4),
        top_p=section.get("top_p", 0.9),
        # Reasoning/larger models need real headroom; never clamp below 4096
        # because reasoning models can spend hundreds of tokens before they
        # emit any visible content, and a connectivity test that fails for
        # that reason hides the real signal we're after.
        num_predict=max(section.get("num_predict", 1200), 4096),
        max_retries=section.get("max_retries", 1),  # fail fast in a connectivity test
        api_key=args.api_key or section.get("api_key", "lm-studio"),
        reasoning_effort=args.reasoning_effort or section.get("reasoning_effort", ""),
    )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_reachable(client) -> bool:
    cfg: LLMConfig = client.cfg
    _section(f"1. Server reachability  ({cfg.provider} at {cfg.host})")
    t0 = time.perf_counter()
    if client.ping():
        dt = (time.perf_counter() - t0) * 1000
        _ok(f"server responded in {dt:.0f} ms")
        return True
    _fail("server did not respond")
    if cfg.provider == "ollama":
        _info("checks: is `ollama serve` running, and is the host/port correct?")
    elif cfg.provider == "lmstudio":
        _info("checks: is LM Studio running with the OpenAI-like server enabled?")
        _info("        toggle it from the 'Developer' / 'Local Server' tab in LM Studio.")
    return False


def check_model_present(client) -> bool:
    cfg: LLMConfig = client.cfg
    _section(f"2. Model availability  ({cfg.model})")
    try:
        names = client.list_models()
    except Exception as e:  # noqa: BLE001
        _fail(f"could not list models: {e!r}")
        return False

    if not names:
        _warn("server responded but reports no loaded models")
        if cfg.provider == "ollama":
            _info(f"pull a model with:  ollama pull {cfg.model}")
        else:
            _info("load a model in LM Studio's 'My Models' tab and start the server.")
        return False

    _info(f"server has {len(names)} model(s) available")
    for n in names[:10]:
        print(f"         - {n}")
    if len(names) > 10:
        print(f"         ... and {len(names) - 10} more")

    target = cfg.model
    matched = (
        target in names
        or any(n == target for n in names)
        or any(n.split(":", 1)[0] == target.split(":", 1)[0] for n in names)
    )
    if matched:
        _ok(f"model '{target}' is available on the server")
        return True

    _fail(f"model '{target}' is NOT available on the server")
    if cfg.provider == "ollama":
        _info(f"pull it with:  ollama pull {target}")
    else:
        _info("load it in LM Studio first, then re-run this test.")
    return False


def check_chat_plain(client) -> bool:
    """Tiny non-JSON chat round-trip to verify generation works."""
    cfg: LLMConfig = client.cfg
    _section("3. Plain chat round-trip  (warm-up)")

    # Use the provider's own raw chat path so we can inspect provider-specific
    # response shapes (Ollama: message.content, LM Studio: choices[0].message).
    system = "You are a terse assistant. Reply with one short sentence."
    user = "Reply with exactly: pong."
    t0 = time.perf_counter()
    try:
        if isinstance(client, OllamaClient):
            raw = client._chat_raw(system, user)  # noqa: SLF001
            msg = raw.get("message") or {}
            content = (msg.get("content") or "").strip()
            thinking = (msg.get("thinking") or "").strip()
            done_reason = raw.get("done_reason", "")
            eval_count = raw.get("eval_count", 0)
            reasoning_tokens = 0
        elif isinstance(client, LMStudioClient):
            raw = client._chat_raw(system, user)  # noqa: SLF001
            choices = raw.get("choices") or []
            choice = choices[0] if choices else {}
            content = ((choice.get("message") or {}).get("content") or "").strip()
            thinking = ""
            done_reason = choice.get("finish_reason", "")
            usage = raw.get("usage") or {}
            eval_count = usage.get("completion_tokens", 0)
            reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        else:  # pragma: no cover - defensive
            _fail(f"unsupported client type: {type(client).__name__}")
            return False
    except Exception as e:  # noqa: BLE001
        _fail(f"chat call failed: {e!r}")
        return False
    dt = time.perf_counter() - t0

    if not content:
        # Reasoning model ate the whole budget on hidden tokens?
        if reasoning_tokens and reasoning_tokens >= max(1, eval_count - 4):
            _fail(
                f"reasoning model spent {reasoning_tokens}/{eval_count} completion "
                f"tokens on hidden reasoning, leaving no room for visible content"
            )
            _info(
                "set [llm].reasoning_effort = \"low\" in your config (or pass "
                "--reasoning-effort low), and/or raise [llm].num_predict to 4096+"
            )
        elif thinking and done_reason == "length":
            _fail("model is a reasoning model and ran out of tokens inside its `thinking` block")
            _info(f"thinking preview: {thinking[:160]!r}")
            _info("raise [llm].num_predict (4096+) or pick a non-reasoning model")
        elif done_reason == "load":
            _fail("first call only returned the load event — try running again")
        elif eval_count == 0:
            _fail("model produced zero output tokens; likely chat-template/stop-token mismatch")
        else:
            _fail(f"chat returned an empty message (finish={done_reason!r})")
        return False

    _ok(f"received {len(content)} chars in {dt:.1f}s")
    if thinking:
        _info(f"(model also produced a {len(thinking)}-char `thinking` block)")
    print(f"         model said: {content[:200]!r}")
    return True


def check_chat_json(client) -> bool:
    """Verify JSON mode works — the pipeline depends on this."""
    _section("4. JSON-mode chat round-trip")
    system = (
        "You are a JSON-only API. Always respond with strict JSON matching the "
        "user's requested shape. No prose, no markdown, no code fences."
    )
    user = (
        "Return a JSON object with two fields: `status` (string, must be the "
        'literal value "ok") and `echo` (string, must be the literal value "pong"). '
        "Do not add any other fields."
    )
    schema = '{"status": "string", "echo": "string"}'

    t0 = time.perf_counter()
    try:
        out = client.chat_json(system, user, schema_hint=schema)
    except LLMError as e:
        _fail(f"chat_json failed: {e!r}")
        return False
    except Exception as e:  # noqa: BLE001
        _fail(f"unexpected error: {e!r}")
        return False
    dt = time.perf_counter() - t0

    _ok(f"received valid JSON in {dt:.1f}s")
    print(f"         parsed: {json.dumps(out, ensure_ascii=False)[:200]}")

    issues = []
    if not isinstance(out, dict):
        issues.append("response is not a JSON object")
    else:
        if "status" not in out or "echo" not in out:
            issues.append("response missing required keys 'status' and/or 'echo'")
        if str(out.get("status", "")).lower() != "ok":
            issues.append(f"status was {out.get('status')!r}, expected 'ok'")
        if str(out.get("echo", "")).lower() != "pong":
            issues.append(f"echo was {out.get('echo')!r}, expected 'pong'")
    for msg in issues:
        _warn(msg)
    if not issues:
        _ok("response matches expected schema and values")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="test_llm_connection",
        description=(
            "Verify the LLM server defined in a TOML config (Ollama or LM Studio) "
            "is reachable, has the configured model loaded, and serves chat "
            "requests in both plain and JSON modes."
        ),
    )
    p.add_argument(
        "--config", "-c",
        default=str(PKG_ROOT / "config.example.toml"),
        help="Path to the TOML config file (default: ../config.example.toml).",
    )
    p.add_argument("--provider", choices=["auto", "ollama", "lmstudio"], default=None)
    p.add_argument("--host", default=None, help="Override [llm].host.")
    p.add_argument("--model", default=None, help="Override [llm].model.")
    p.add_argument("--api-key", default=None, help="LM Studio API key (any string).")
    p.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default=None,
        help="Reasoning-model budget knob (low/medium/high).",
    )
    p.add_argument("--timeout", type=int, default=None, help="Override [llm].timeout_s.")
    p.add_argument("--skip-plain", action="store_true", help="Skip phase 3.")
    p.add_argument("--skip-json", action="store_true", help="Skip phase 4.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg_path = Path(args.config).resolve()

    print(f"{BOLD}LLM connectivity test{RESET}")
    print(f"  config: {cfg_path}")
    toml_cfg = _load_config(cfg_path)
    cfg = _build_llm_config(toml_cfg, args)

    try:
        client = make_client(cfg)
    except LLMError as e:
        print(f"\n{RED}error:{RESET} {e}")
        return 3

    # cfg has been mutated by make_client to contain the resolved provider/host.
    print(f"  provider: {cfg.provider}")
    print(f"  host:     {cfg.host}")
    print(f"  model:    {cfg.model}")
    print(f"  timeout:  {cfg.timeout_s}s")

    if not check_reachable(client):
        return 3
    if not check_model_present(client):
        return 4

    if not args.skip_plain:
        if not check_chat_plain(client):
            return 5
    else:
        _section("3. Plain chat round-trip")
        _info("skipped (--skip-plain)")

    if not args.skip_json:
        if not check_chat_json(client):
            return 5
    else:
        _section("4. JSON-mode chat round-trip")
        _info("skipped (--skip-json)")

    print(f"\n{GREEN}{BOLD}All checks passed.{RESET}  {cfg.provider} is ready for prompt_forge.\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        raise SystemExit(130)
