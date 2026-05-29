"""Local web UI server for prompt_forge.

Pure-stdlib HTTP server that serves a single-page UI for configuring and
running the prompt_forge pipeline. Binds to 127.0.0.1 only.

Endpoints
---------
GET  /                           - serves ui/index.html
GET  /api/config                 - returns saved config.json (or defaults)
POST /api/config                 - atomically writes config.json
GET  /api/defaults               - returns the built-in default config
POST /api/test-connection        - {provider, host, model?} -> {ok, models?}
POST /api/list-models            - {provider, host} -> {models}
POST /api/run                    - {args:[...]} -> {run_id}
GET  /api/runs/{id}/stream       - Server-Sent Events log stream
POST /api/runs/{id}/cancel       - SIGTERM the subprocess (then SIGKILL)
GET  /api/runs/{id}/status       - {state, exit_code?}
GET  /api/browse?path=...        - directory listing for a poor-man's file picker
GET  /api/inspect-input?path=... - returns deck/set structure of an input JSON
GET  /api/cache-status?...       - reports which (deck,set) pairs have a usable cache
POST /api/build-from-cache       - assemble an output JSON from cached checkpoints
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .llm_client import LLMConfig, make_client

log = logging.getLogger(__name__)

# Project root = parent of the prompt_forge package directory. We resolve this
# at import time so the server can find ui/index.html and the default
# config.json location regardless of the current working directory.
_PKG_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PKG_DIR.parent
_UI_DIR = _PKG_DIR / "ui"
_CONFIG_PATH = _PROJECT_ROOT / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    # Files
    "input": "",
    "output": "",
    # Target
    "target": "flux",
    "variant": "",
    # Selection
    "process_all": True,
    "hide_completed": False,
    "deck": "",
    "set_name": "",
    # Provider
    "provider": "auto",
    "host": "",
    "model": "",
    "api_key": "lm-studio",
    "reasoning_effort": "",
    "context_length": 8192,
    # Stripper provider (optional — separate LLM for boilerplate stripping)
    "stripper_provider": "",
    "stripper_host": "",
    "stripper_model": "",
    "stripper_api_key": "",
    # Tuning
    "timeout_s": 240,
    "temperature": 0.4,
    "num_predict": 1200,
    "concurrency": 2,
    # Pipeline
    "checkpoint_dir": ".forge_cache",
    "recompute_boilerplate": True,
    "validate": True,
    # Misc
    "dry_run": False,
    "verbose": 1,  # 0=warn, 1=info, 2=debug
}


# ---------------------------------------------------------------------------
# Run manager: spawns CLI as a subprocess and streams its output to listeners.
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self, run_id: str, cmd: list[str]):
        self.run_id = run_id
        self.cmd = cmd
        self.proc: subprocess.Popen | None = None
        self.lines: list[str] = []          # full backlog for late-joining streams
        self.listeners: list[queue.Queue[str | None]] = []
        self.lock = threading.Lock()
        self.state = "starting"             # starting | running | done | cancelled | failed
        self.exit_code: int | None = None
        self.started_at = time.time()
        self.ended_at: float | None = None

    def add_listener(self) -> queue.Queue[str | None]:
        q: queue.Queue[str | None] = queue.Queue()
        with self.lock:
            # Replay backlog so reconnecting clients see prior output.
            for line in self.lines:
                q.put(line)
            if self.state in ("done", "cancelled", "failed"):
                q.put(None)
            else:
                self.listeners.append(q)
        return q

    def remove_listener(self, q: queue.Queue[str | None]) -> None:
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def emit(self, line: str) -> None:
        with self.lock:
            self.lines.append(line)
            for q in self.listeners:
                q.put(line)

    def finish(self, code: int, label: str) -> None:
        with self.lock:
            self.exit_code = code
            self.state = label
            self.ended_at = time.time()
            for q in self.listeners:
                q.put(None)
            self.listeners.clear()


class RunManager:
    """One concurrent run at a time. New requests while busy are rejected."""

    def __init__(self) -> None:
        self.runs: dict[str, _Run] = {}
        self.active_id: str | None = None
        self.lock = threading.Lock()

    def is_busy(self) -> bool:
        with self.lock:
            return self.active_id is not None

    def start(self, cmd: list[str], cwd: Path) -> _Run:
        with self.lock:
            if self.active_id is not None:
                raise RuntimeError("Another run is already in progress.")
            run_id = uuid.uuid4().hex[:12]
            run = _Run(run_id, cmd)
            self.runs[run_id] = run
            self.active_id = run_id

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                env=env,
            )
        except OSError as e:
            run.emit(f"[launch error] {e}")
            run.finish(127, "failed")
            with self.lock:
                self.active_id = None
            return run

        run.proc = proc
        run.state = "running"
        run.emit(f"$ {' '.join(cmd)}")
        threading.Thread(target=self._reader, args=(run,), daemon=True).start()
        return run

    def _reader(self, run: _Run) -> None:
        assert run.proc is not None
        try:
            assert run.proc.stdout is not None
            for raw in run.proc.stdout:
                run.emit(raw.rstrip("\r\n"))
        except Exception as e:  # pragma: no cover - defensive
            run.emit(f"[reader error] {e}")
        code = run.proc.wait()
        label = "cancelled" if run.state == "cancelling" else (
            "done" if code == 0 else "failed"
        )
        run.finish(code, label)
        with self.lock:
            if self.active_id == run.run_id:
                self.active_id = None

    def cancel(self, run_id: str) -> bool:
        run = self.runs.get(run_id)
        if not run or not run.proc or run.state not in ("running", "starting"):
            return False
        run.state = "cancelling"
        run.emit("[cancel requested]")
        try:
            run.proc.terminate()
        except ProcessLookupError:
            return True

        def _kill_after_grace() -> None:
            time.sleep(5.0)
            if run.proc and run.proc.poll() is None:
                run.emit("[grace period elapsed, sending SIGKILL]")
                try:
                    run.proc.kill()
                except ProcessLookupError:
                    pass

        threading.Thread(target=_kill_after_grace, daemon=True).start()
        return True


_RUNS = RunManager()


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def load_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        loaded = json.loads(_CONFIG_PATH.read_text("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("config.json must contain a JSON object")
    except (OSError, ValueError, json.JSONDecodeError) as e:
        log.warning("Could not read %s (%s); using defaults", _CONFIG_PATH, e)
        return dict(DEFAULT_CONFIG)
    # Merge over defaults so newly added keys appear.
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in loaded.items() if k in DEFAULT_CONFIG})
    return merged


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(DEFAULT_CONFIG)
    for k, default in DEFAULT_CONFIG.items():
        if k in cfg:
            sanitized[k] = _coerce(cfg[k], default)
    tmp = _CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sanitized, indent=2), "utf-8")
    tmp.replace(_CONFIG_PATH)
    return sanitized


def _coerce(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if value is None:
        return default
    return str(value)


# ---------------------------------------------------------------------------
# Build the CLI argv from a config dict
# ---------------------------------------------------------------------------

def build_argv(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (argv, warnings). argv is everything after `python -m prompt_forge`."""
    warnings: list[str] = []
    argv: list[str] = []

    inp = (cfg.get("input") or "").strip()
    if not inp:
        raise ValueError("Input file is required.")
    argv += ["--input", inp]

    out = (cfg.get("output") or "").strip()
    if out:
        argv += ["--output", out]

    target = cfg.get("target") or "flux"
    argv += ["--target", target]

    variant = (cfg.get("variant") or "").strip()
    if variant:
        argv += ["--variant", variant]

    if cfg.get("process_all"):
        argv += ["--all"]
    else:
        deck = (cfg.get("deck") or "").strip()
        set_name = (cfg.get("set_name") or "").strip()
        # Sentinel '__ALL__' from the UI's <All sets> dropdown means
        # "every set in this deck" -- pass --deck without --set.
        if set_name == "__ALL__":
            set_name = ""
        if not deck:
            raise ValueError(
                "Specify either 'Process all', or pick a Deck (and optionally a Set)."
            )
        argv += ["--deck", deck]
        if set_name:
            argv += ["--set", set_name]

    provider = cfg.get("provider") or "auto"
    argv += ["--provider", provider]

    host = (cfg.get("host") or "").strip()
    if host:
        argv += ["--host", host]
    model = (cfg.get("model") or "").strip()
    if model:
        argv += ["--model", model]
    if provider == "lmstudio":
        api_key = (cfg.get("api_key") or "").strip()
        if api_key:
            argv += ["--api-key", api_key]

    re_eff = (cfg.get("reasoning_effort") or "").strip()
    if re_eff:
        argv += ["--reasoning-effort", re_eff]

    ctx = cfg.get("context_length")
    if ctx:
        argv += ["--context-length", str(int(ctx))]

    # Stripper provider (optional — separate LLM for boilerplate stripping)
    sprov = (cfg.get("stripper_provider") or "").strip()
    shost = (cfg.get("stripper_host") or "").strip()
    smodel = (cfg.get("stripper_model") or "").strip()
    if sprov:
        argv += ["--stripper-provider", sprov]
    if shost:
        argv += ["--stripper-host", shost]
    if smodel:
        argv += ["--stripper-model", smodel]
    if sprov == "lmstudio":
        skey = (cfg.get("stripper_api_key") or "").strip()
        if skey:
            argv += ["--stripper-api-key", skey]

    if cfg.get("timeout_s"):
        argv += ["--timeout", str(int(cfg["timeout_s"]))]
    if cfg.get("temperature") is not None and cfg.get("temperature") != "":
        argv += ["--temperature", str(float(cfg["temperature"]))]
    if cfg.get("num_predict"):
        argv += ["--num-predict", str(int(cfg["num_predict"]))]
    if cfg.get("concurrency"):
        argv += ["--concurrency", str(int(cfg["concurrency"]))]

    ckpt = (cfg.get("checkpoint_dir") or "").strip()
    if ckpt:
        argv += ["--checkpoint-dir", ckpt]
    if cfg.get("recompute_boilerplate") is False:
        argv += ["--no-recompute-boilerplate"]
    if cfg.get("validate") is False:
        argv += ["--no-validate"]
    if cfg.get("dry_run"):
        argv += ["--dry-run"]

    verbose = int(cfg.get("verbose") or 0)
    if verbose >= 2:
        argv += ["-vv"]
    elif verbose == 1:
        argv += ["-v"]

    return argv, warnings


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "PromptForgeUI/0.3"

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs
        log.info("%s - %s", self.address_string(), fmt % args)

    # -- response helpers ---------------------------------------------------

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, content_type: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("expected JSON object")
        return obj

    # -- routing ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        try:
            if u.path == "/" or u.path == "/index.html":
                self._serve_index()
            elif u.path == "/api/config":
                self._json(load_config())
            elif u.path == "/api/defaults":
                self._json(DEFAULT_CONFIG)
            elif u.path.startswith("/api/runs/") and u.path.endswith("/stream"):
                run_id = u.path.split("/")[3]
                self._stream_run(run_id)
            elif u.path.startswith("/api/runs/") and u.path.endswith("/status"):
                run_id = u.path.split("/")[3]
                self._run_status(run_id)
            elif u.path == "/api/browse":
                qs = parse_qs(u.query)
                self._browse(qs.get("path", [""])[0])
            elif u.path == "/api/inspect-input":
                qs = parse_qs(u.query)
                self._inspect_input(qs.get("path", [""])[0])
            elif u.path == "/api/cache-status":
                qs = parse_qs(u.query)
                self._cache_status(
                    qs.get("input", [""])[0],
                    qs.get("checkpoint_dir", [""])[0],
                    qs.get("target", [""])[0],
                )
            elif u.path == "/healthz":
                self._json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "no such endpoint")
        except Exception as e:  # noqa: BLE001
            log.exception("GET %s failed", u.path)
            self._json({"error": str(e)}, 500)

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        try:
            if u.path == "/api/config":
                body = self._read_json()
                saved = save_config(body)
                self._json({"ok": True, "config": saved})
            elif u.path == "/api/test-connection":
                body = self._read_json()
                self._json(self._test_connection(body))
            elif u.path == "/api/list-models":
                body = self._read_json()
                self._json(self._list_models(body))
            elif u.path == "/api/run":
                body = self._read_json()
                self._json(self._start_run(body))
            elif u.path.startswith("/api/runs/") and u.path.endswith("/cancel"):
                run_id = u.path.split("/")[3]
                ok = _RUNS.cancel(run_id)
                self._json({"ok": ok})
            elif u.path == "/api/build-from-cache":
                body = self._read_json()
                self._json(self._build_from_cache(body))
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "no such endpoint")
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            log.exception("POST %s failed", u.path)
            self._json({"error": str(e)}, 500)

    # -- handlers -----------------------------------------------------------

    def _serve_index(self) -> None:
        index = _UI_DIR / "index.html"
        if not index.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "ui/index.html missing")
            return
        self._text(index.read_text("utf-8"), "text/html")

    def _make_llm_cfg(self, body: dict[str, Any]) -> LLMConfig:
        provider = (body.get("provider") or "auto").strip()
        host = (body.get("host") or "").strip()
        model = (body.get("model") or "").strip()
        api_key = (body.get("api_key") or "lm-studio").strip()
        return LLMConfig(
            provider=provider,
            host=host,
            model=model,
            timeout_s=15,
            temperature=0.4,
            top_p=0.9,
            num_predict=64,
            max_retries=1,
            api_key=api_key,
            reasoning_effort="",
        )

    def _test_connection(self, body: dict[str, Any]) -> dict[str, Any]:
        cfg = self._make_llm_cfg(body)
        try:
            client = make_client(cfg)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"init failed: {e}"}
        ok = False
        try:
            ok = client.ping()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"ping failed: {e}"}
        models: list[str] = []
        if ok:
            try:
                models = client.list_models()
            except Exception as e:  # noqa: BLE001
                return {"ok": True, "models": [], "warning": f"could not list models: {e}"}
        return {"ok": ok, "models": models, "host": cfg.host, "provider": cfg.provider}

    def _list_models(self, body: dict[str, Any]) -> dict[str, Any]:
        cfg = self._make_llm_cfg(body)
        try:
            client = make_client(cfg)
            return {"models": client.list_models(), "provider": cfg.provider, "host": cfg.host}
        except Exception as e:  # noqa: BLE001
            return {"models": [], "error": str(e)}

    def _start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        if _RUNS.is_busy():
            raise ValueError("A run is already in progress. Cancel it first.")
        cfg_overrides = body.get("config") or {}
        cfg = load_config()
        cfg.update({k: v for k, v in cfg_overrides.items() if k in DEFAULT_CONFIG})
        # Persist the launch config so the UI's "saved" state matches what ran.
        save_config(cfg)

        argv, warnings = build_argv(cfg)
        cmd = [sys.executable, "-u", "-m", "prompt_forge", *argv]
        run = _RUNS.start(cmd, cwd=_PROJECT_ROOT)
        return {"run_id": run.run_id, "cmd": cmd, "warnings": warnings}

    def _run_status(self, run_id: str) -> None:
        run = _RUNS.runs.get(run_id)
        if not run:
            self._json({"error": "no such run"}, 404)
            return
        self._json({
            "state": run.state,
            "exit_code": run.exit_code,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
        })

    def _stream_run(self, run_id: str) -> None:
        run = _RUNS.runs.get(run_id)
        if not run:
            self.send_error(HTTPStatus.NOT_FOUND, "no such run")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = run.add_listener()
        try:
            # Heartbeat to detect dead clients quickly.
            last_beat = time.time()
            while True:
                try:
                    line = q.get(timeout=10.0)
                except queue.Empty:
                    self._sse_write(":heartbeat\n\n")
                    last_beat = time.time()
                    continue
                if line is None:
                    self._sse_write(
                        f"event: done\ndata: {json.dumps({'state': run.state, 'exit_code': run.exit_code})}\n\n"
                    )
                    break
                self._sse_write(f"data: {json.dumps(line)}\n\n")
                if time.time() - last_beat > 10:
                    last_beat = time.time()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            run.remove_listener(q)

    def _sse_write(self, chunk: str) -> None:
        try:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise

    def _inspect_input(self, path: str) -> None:
        """Parse an input JSON file and return its deck/set tree.

        Response shape::

            {
              "path": "...",
              "decks": [
                {
                  "label": "<display_name or model_name>",
                  "value": "<display_name or model_name>",  // what the CLI consumes
                  "sets": [
                    {"label": "<name (abbr)>", "value": "<name>", "prompt_count": N},
                    ...
                  ]
                }
              ]
            }
        """
        if not path:
            self._json({"error": "path is required"}, 400)
            return
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = (_PROJECT_ROOT / target).resolve()
        if not target.exists():
            self._json({"error": f"no such file: {target}"}, 404)
            return
        if target.is_dir():
            self._json({"error": f"path is a directory: {target}"}, 400)
            return
        try:
            data = json.loads(target.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self._json({"error": f"could not parse JSON: {e}"}, 400)
            return
        decks_in = data.get("decks") if isinstance(data, dict) else None
        if not isinstance(decks_in, list):
            self._json({"error": "input JSON has no top-level 'decks' array"}, 400)
            return
        decks_out: list[dict[str, Any]] = []
        for d in decks_in:
            if not isinstance(d, dict):
                continue
            label = (
                d.get("display_name")
                or d.get("model_name")
                or f"deck #{len(decks_out) + 1}"
            )
            # The CLI matches deck by display_name OR model_name (case-insensitive
            # substring). We send display_name first because it's friendlier.
            value = d.get("display_name") or d.get("model_name") or label
            sets_out: list[dict[str, Any]] = []
            for s in (d.get("sets") or []):
                if not isinstance(s, dict):
                    continue
                name = s.get("name") or s.get("abbr") or ""
                abbr = s.get("abbr") or ""
                set_label = name
                if abbr and abbr != name:
                    set_label = f"{name} ({abbr})" if name else abbr
                sets_out.append({
                    "label": set_label or "(unnamed set)",
                    "value": name or abbr,
                    "prompt_count": len(s.get("prompts") or []),
                })
            decks_out.append({
                "label": str(label),
                "value": str(value),
                "model_name": d.get("model_name") or "",
                "display_name": d.get("display_name") or "",
                "set_count": len(sets_out),
                "sets": sets_out,
            })
        self._json({"path": str(target), "decks": decks_out})

    # -- cache helpers ------------------------------------------------------

    def _resolve_checkpoint_dir(self, checkpoint_dir: str) -> Path:
        """Resolve the checkpoint dir the same way the CLI does.

        Empty -> the package default (.forge_cache under project root).
        Relative -> resolved against the project root.
        """
        if not checkpoint_dir:
            checkpoint_dir = ".forge_cache"
        p = Path(checkpoint_dir).expanduser()
        if not p.is_absolute():
            p = (_PROJECT_ROOT / p).resolve()
        return p

    @staticmethod
    def _is_prompt_complete(p: Any, target: str) -> bool:
        """Mirrors Pipeline._is_prompt_complete (kept local to avoid importing
        the heavy pipeline module just for cache inspection)."""
        if target == "flux":
            return isinstance(p, list) and len(p) == 2 and bool(p[0]) and bool(p[1])
        return (
            isinstance(p, dict)
            and isinstance(p.get("positive_tags"), list)
            and bool(p["positive_tags"])
            and isinstance(p.get("negative_tags"), list)
            and bool(p["negative_tags"])
        )

    def _read_checkpoint(self, ckpt_dir: Path, deck_idx: int, set_idx: int) -> dict | None:
        p = ckpt_dir / f"deck{deck_idx:02d}_set{set_idx:02d}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _classify_set(self, ckpt: dict | None, expected_target: str, prompt_count: int) -> dict:
        """Return {has_cache, target_match, all_prompts_written, completed}.

        Cache is considered 'completed' for the UI hide filter when every
        prompt in the source set is present and complete in the checkpoint
        AND the checkpoint's target matches the active run target.
        """
        if not ckpt:
            return {"has_cache": False, "target_match": False,
                    "all_prompts_written": False, "completed": False}
        ck_target = ckpt.get("target") or ""
        target_match = (not expected_target) or (ck_target == expected_target)
        prompts = ckpt.get("prompts") or []
        all_written = (
            len(prompts) >= prompt_count
            and all(self._is_prompt_complete(p, ck_target) for p in prompts[:prompt_count])
            and prompt_count > 0
        )
        completed = bool(ckpt.get("completed", False))
        return {
            "has_cache": True,
            "target_match": target_match,
            "all_prompts_written": all_written,
            "completed": completed,
            "cache_target": ck_target,
            "cached_prompt_count": len(prompts),
        }

    def _cache_status(self, input_path: str, checkpoint_dir: str, target: str) -> None:
        """Report per-(deck,set) cache state for the given input + cache dir.

        Response shape::

            {
              "input": "...",
              "checkpoint_dir": "...",
              "target": "flux"|"sdxl"|"",
              "decks": [
                {
                  "deck_idx": 0,
                  "value": "<display_name or model_name>",
                  "all_sets_complete": bool,
                  "sets": [
                    {"set_idx": 0, "value": "<set name>",
                     "prompt_count": N, "has_cache": bool,
                     "target_match": bool, "all_prompts_written": bool,
                     "completed": bool}
                  ]
                }
              ]
            }
        """
        if not input_path:
            self._json({"error": "input is required"}, 400)
            return
        in_path = Path(input_path).expanduser()
        if not in_path.is_absolute():
            in_path = (_PROJECT_ROOT / in_path).resolve()
        if not in_path.exists():
            self._json({"error": f"no such file: {in_path}"}, 404)
            return
        try:
            data = json.loads(in_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self._json({"error": f"could not parse JSON: {e}"}, 400)
            return
        decks_in = data.get("decks") if isinstance(data, dict) else None
        if not isinstance(decks_in, list):
            self._json({"error": "input JSON has no top-level 'decks' array"}, 400)
            return
        ckpt_dir = self._resolve_checkpoint_dir(checkpoint_dir)
        decks_out: list[dict[str, Any]] = []
        for di, d in enumerate(decks_in):
            if not isinstance(d, dict):
                continue
            sets_out: list[dict[str, Any]] = []
            for si, s in enumerate(d.get("sets") or []):
                if not isinstance(s, dict):
                    continue
                pcount = len(s.get("prompts") or [])
                ckpt = self._read_checkpoint(ckpt_dir, di, si)
                cls = self._classify_set(ckpt, target, pcount)
                sets_out.append({
                    "set_idx": si,
                    "value": s.get("name") or s.get("abbr") or "",
                    "prompt_count": pcount,
                    **cls,
                })
            # Hide-filter rule (per user spec): "All prompts written" plus
            # target-match counts as 'complete enough to hide'.
            all_done = bool(sets_out) and all(
                s["all_prompts_written"] and s["target_match"] for s in sets_out
            )
            decks_out.append({
                "deck_idx": di,
                "value": d.get("display_name") or d.get("model_name") or f"deck #{di + 1}",
                "all_sets_complete": all_done,
                "sets": sets_out,
            })
        self._json({
            "input": str(in_path),
            "checkpoint_dir": str(ckpt_dir),
            "checkpoint_dir_exists": ckpt_dir.exists(),
            "target": target or "",
            "decks": decks_out,
        })

    def _build_from_cache(self, body: dict[str, Any]) -> dict[str, Any]:
        """Assemble an output JSON from cached checkpoints, no LLM calls.

        Body: {input, output (optional), target, checkpoint_dir (optional)}.
        For each (deck, set) where the checkpoint matches the active target
        and all prompts are written, we splice ckpt.prompts (and ckpt.boilerplate
        when present) into the source structure. Sets without a usable cache
        are left as-is, so the output is a 'best so far' snapshot.
        """
        input_path = (body.get("input") or "").strip()
        if not input_path:
            raise ValueError("'input' is required")
        target = (body.get("target") or "flux").strip().lower()
        if target not in ("flux", "sdxl"):
            raise ValueError("'target' must be 'flux' or 'sdxl'")
        in_path = Path(input_path).expanduser()
        if not in_path.is_absolute():
            in_path = (_PROJECT_ROOT / in_path).resolve()
        if not in_path.exists():
            raise ValueError(f"no such file: {in_path}")
        data = json.loads(in_path.read_text("utf-8"))
        decks_in = data.get("decks") if isinstance(data, dict) else None
        if not isinstance(decks_in, list):
            raise ValueError("input JSON has no top-level 'decks' array")
        ckpt_dir = self._resolve_checkpoint_dir(body.get("checkpoint_dir") or "")

        out_path_raw = (body.get("output") or "").strip()
        if out_path_raw:
            out_path = Path(out_path_raw).expanduser()
            if not out_path.is_absolute():
                out_path = (_PROJECT_ROOT / out_path).resolve()
        else:
            out_path = in_path.with_name(f"{in_path.stem}.{target}.json")

        sets_total = sets_filled = sets_skipped_target = sets_no_cache = 0
        sets_partial = 0
        details: list[dict[str, Any]] = []
        for di, d in enumerate(decks_in):
            if not isinstance(d, dict):
                continue
            for si, s in enumerate(d.get("sets") or []):
                if not isinstance(s, dict):
                    continue
                sets_total += 1
                pcount = len(s.get("prompts") or [])
                ckpt = self._read_checkpoint(ckpt_dir, di, si)
                if ckpt is None:
                    sets_no_cache += 1
                    details.append({"deck_idx": di, "set_idx": si,
                                     "value": s.get("name") or "",
                                     "status": "no_cache"})
                    continue
                ck_target = ckpt.get("target") or ""
                if ck_target and ck_target != target:
                    sets_skipped_target += 1
                    details.append({"deck_idx": di, "set_idx": si,
                                     "value": s.get("name") or "",
                                     "status": "target_mismatch",
                                     "cache_target": ck_target})
                    continue
                ck_prompts = ckpt.get("prompts") or []
                all_written = (
                    len(ck_prompts) >= pcount
                    and all(self._is_prompt_complete(p, target) for p in ck_prompts[:pcount])
                    and pcount > 0
                )
                if not all_written:
                    sets_partial += 1
                    details.append({"deck_idx": di, "set_idx": si,
                                     "value": s.get("name") or "",
                                     "status": "partial",
                                     "cached_prompt_count": len(ck_prompts),
                                     "prompt_count": pcount})
                    continue
                # Splice in the rewritten prompts (truncate to source length).
                s["prompts"] = list(ck_prompts[:pcount])
                if ckpt.get("boilerplate"):
                    s["boilerplate"] = ckpt["boilerplate"]
                sets_filled += 1
                details.append({"deck_idx": di, "set_idx": si,
                                 "value": s.get("name") or "",
                                 "status": "filled",
                                 "prompt_count": pcount})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
        )
        return {
            "ok": True,
            "output": str(out_path),
            "target": target,
            "checkpoint_dir": str(ckpt_dir),
            "summary": {
                "sets_total": sets_total,
                "sets_filled_from_cache": sets_filled,
                "sets_partial": sets_partial,
                "sets_no_cache": sets_no_cache,
                "sets_target_mismatch": sets_skipped_target,
            },
            "details": details,
        }

    def _browse(self, path: str) -> None:
        """Lightweight directory listing for the UI's file picker."""
        target = Path(path).expanduser() if path else _PROJECT_ROOT
        if not target.is_absolute():
            target = (_PROJECT_ROOT / target).resolve()
        if not target.exists():
            self._json({"error": f"no such path: {target}"}, 404)
            return
        if target.is_file():
            target = target.parent
        try:
            entries = []
            for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    is_dir = child.is_dir()
                except OSError:
                    continue
                entries.append({
                    "name": child.name,
                    "path": str(child),
                    "is_dir": is_dir,
                    "size": (child.stat().st_size if not is_dir else None),
                })
        except PermissionError as e:
            self._json({"error": str(e)}, 403)
            return
        self._json({
            "cwd": str(target),
            "parent": str(target.parent) if target.parent != target else None,
            "entries": entries,
        })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    if not _UI_DIR.exists():
        log.error("UI assets missing: %s", _UI_DIR)
        return 2
    httpd = ThreadingHTTPServer((host, port), _Handler)
    url = f"http://{host}:{port}/"
    log.info("prompt_forge UI listening on %s", url)
    print(f"prompt_forge UI listening on {url}", file=sys.stderr)
    print(f"config.json: {_CONFIG_PATH}", file=sys.stderr)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down...", file=sys.stderr)
    finally:
        httpd.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="prompt_forge.ui", description="Local web UI for prompt_forge.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--verbose", "-v", action="count", default=1)
    args = p.parse_args(argv)

    level = logging.WARNING if args.verbose == 0 else (
        logging.INFO if args.verbose == 1 else logging.DEBUG
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return serve(args.host, args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
