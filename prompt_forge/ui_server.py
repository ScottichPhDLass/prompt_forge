"""Local web UI server for prompt_forge.

Pure-stdlib HTTP server that serves a single-page UI for configuring and
running the prompt_forge pipeline.

Binds to 127.0.0.1 by default. Pass ``--host 0.0.0.0`` (or a specific NIC
IP) to expose the UI on the local network. There is no authentication —
only enable LAN binding on networks you trust.

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
import socket
import ssl
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

from .llm_client import LLMConfig, LLMError, make_client

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
# Security: API key authentication
# ---------------------------------------------------------------------------

def _get_api_key() -> str | None:
    """Get the API key from environment variable. Returns None if not set."""
    return os.environ.get("PROMPT_FORGE_API_KEY")


def _validate_auth(handler: "BaseHTTPRequestHandler") -> bool:
    """Check if request has valid API key. /healthz endpoint bypassed.
    
    If PROMPT_FORGE_API_KEY is set, all requests except /healthz must include
    a valid Authorization header: "Authorization: Bearer {key}"
    """
    api_key = _get_api_key()
    if not api_key:
        return True  # Auth disabled if env var not set
    
    path = handler.path.split("?")[0]
    if path == "/healthz":
        return True  # Health check always allowed
    
    auth_header = handler.headers.get("Authorization", "")
    expected_header = f"Bearer {api_key}"
    
    return auth_header == expected_header


# ---------------------------------------------------------------------------
# Security: Path sanitization (prevent directory traversal)
# ---------------------------------------------------------------------------

def _sanitize_path(path_input: str, base_dir: Path = _PROJECT_ROOT) -> Path:
    """Resolve and validate a user-provided path stays within base_dir.
    
    Raises ValueError if path escapes base_dir or doesn't exist/is not readable.
    Resolves symlinks to detect traversal attacks.
    """
    if not path_input:
        return base_dir
    
    # Expand ~ and resolve to absolute path
    target = Path(path_input).expanduser()
    if not target.is_absolute():
        target = base_dir / target
    
    # Resolve symlinks to their real path (protects against symlink escapes)
    try:
        real_target = target.resolve()
        real_base = base_dir.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Could not resolve path: {e}") from e
    
    # Verify resolved path is within base directory
    try:
        real_target.relative_to(real_base)
    except ValueError:
        raise ValueError(f"Path traversal denied: {path_input}")
    
    return real_target


# ---------------------------------------------------------------------------
# Security: Logging filter (redact sensitive information)
# ---------------------------------------------------------------------------

class _SecretsFilter(logging.Filter):
    """Redact API keys, AWS credentials, and other sensitive patterns from logs."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(str(v)) for v in record.args)
        return True
    
    @staticmethod
    def _redact(text: str) -> str:
        """Redact sensitive patterns: AWS keys, API keys, tokens, bearer tokens."""
        import re
        # AWS Access Key ID: AKIA followed by 16 alphanumeric chars
        text = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", text)
        # AWS Secret Access Key: usually 40 chars of base64-like
        text = re.sub(r"aws_secret_access_key['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9+/=]{40}['\"]?", "[REDACTED_AWS_SECRET]", text)
        # Bearer tokens
        text = re.sub(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer [REDACTED_TOKEN]", text)
        # API keys in headers or config (sk-, pk-, etc.)
        text = re.sub(r"['\"]?(api[_-]?key|sk_[a-z]{3,}|pk_[a-z]{3,})['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9\-._]+['\"]?", "[REDACTED_API_KEY]", text)
        # Generic credential patterns
        text = re.sub(r"password['\"]?\s*[:=]\s*['\"][^\"']+['\"]", "password: [REDACTED]", text, flags=re.IGNORECASE)
        return text


# ---------------------------------------------------------------------------
# Security: Input validation (DoS prevention)
# ---------------------------------------------------------------------------

def _validate_numeric_param(value: Any, name: str, min_val: int | float, max_val: int | float) -> int | float:
    """Validate and coerce a numeric parameter to be within bounds."""
    try:
        num = float(value) if isinstance(value, str) else value
        if not isinstance(num, (int, float)):
            raise ValueError(f"{name} must be numeric")
        if num < min_val or num > max_val:
            raise ValueError(f"{name} must be between {min_val} and {max_val}, got {num}")
        return int(num) if isinstance(min_val, int) else num
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid {name}: {e}") from e


def _validate_content_type(handler: "BaseHTTPRequestHandler") -> bool:
    """Verify Content-Type header is present and is application/json for POST."""
    if handler.command != "POST":
        return True
    
    content_type = handler.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if content_type and content_type not in ("application/json", "application/json"):
        return False
    return True


def _validate_json_size(handler: "BaseHTTPRequestHandler", max_bytes: int = 10_000_000) -> bool:
    """Check Content-Length doesn't exceed max_bytes (prevent memory exhaustion)."""
    try:
        content_length = int(handler.headers.get("Content-Length", "0") or "0")
        return content_length <= max_bytes
    except ValueError:
        return False


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

        # Create a clean environment with only whitelisted variables
        # to prevent leaking secrets (AWS keys, API tokens, etc.) to subprocess
        env = {}
        for var in ("PATH", "HOME", "LANG", "TZ"):
            if var in os.environ:
                env[var] = os.environ[var]
        env["PYTHONUNBUFFERED"] = "1"
        
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
    if provider in ("lmstudio", "gemini", "deepseek", "openai"):
        api_key = (cfg.get("api_key") or "").strip()
        if api_key and api_key != "lm-studio":
            argv += ["--api-key", api_key]
        elif provider != "lmstudio":
            # For remote providers, default to the configured key even if it's
            # the lm-studio placeholder — user may have set a real key.
            argv += ["--api-key", api_key or ""]

    re_eff = (cfg.get("reasoning_effort") or "").strip()
    if re_eff:
        argv += ["--reasoning-effort", re_eff]

    # Validate and add numeric parameters with bounds checking
    if cfg.get("timeout_s"):
        timeout_s = _validate_numeric_param(cfg["timeout_s"], "timeout_s", 0, 3600)
        argv += ["--timeout", str(int(timeout_s))]
    
    if cfg.get("temperature") is not None and cfg.get("temperature") != "":
        temperature = _validate_numeric_param(cfg["temperature"], "temperature", 0.0, 2.0)
        argv += ["--temperature", str(temperature)]
    
    if cfg.get("num_predict"):
        num_predict = _validate_numeric_param(cfg["num_predict"], "num_predict", 1, 1_000_000)
        argv += ["--num-predict", str(int(num_predict))]
    
    if cfg.get("concurrency"):
        concurrency = _validate_numeric_param(cfg["concurrency"], "concurrency", 1, 256)
        argv += ["--concurrency", str(int(concurrency))]

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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, content_type: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        # Validate Content-Type for POST requests
        if not _validate_content_type(self):
            raise ValueError("Content-Type must be application/json")
        
        # Validate request size to prevent memory exhaustion
        if not _validate_json_size(self):
            raise ValueError("Request body too large (max 10MB)")
        
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
        # Check authentication first
        if not _validate_auth(self):
            self._json({"error": "Unauthorized"}, 401)
            return
        
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
        # Check authentication first
        if not _validate_auth(self):
            self._json({"error": "Unauthorized"}, 401)
            return
        
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
        except LLMError as e:
            return {"ok": False, "error": str(e)}
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
        try:
            target = _sanitize_path(path)
        except ValueError as e:
            self._json({"error": str(e)}, 403)
            return
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
        Validates path stays within project root.
        """
        if not checkpoint_dir:
            checkpoint_dir = ".forge_cache"
        try:
            return _sanitize_path(checkpoint_dir)
        except ValueError as e:
            raise ValueError(f"Invalid checkpoint directory: {e}") from e

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
        try:
            in_path = _sanitize_path(input_path)
        except ValueError as e:
            self._json({"error": str(e)}, 403)
            return
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
        try:
            in_path = _sanitize_path(input_path)
        except ValueError as e:
            raise ValueError(f"Invalid input path: {e}") from e
        if not in_path.exists():
            raise ValueError(f"no such file: {in_path}")
        data = json.loads(in_path.read_text("utf-8"))
        decks_in = data.get("decks") if isinstance(data, dict) else None
        if not isinstance(decks_in, list):
            raise ValueError("input JSON has no top-level 'decks' array")
        ckpt_dir = self._resolve_checkpoint_dir(body.get("checkpoint_dir") or "")

        out_path_raw = (body.get("output") or "").strip()
        if out_path_raw:
            try:
                out_path = _sanitize_path(out_path_raw)
            except ValueError as e:
                raise ValueError(f"Invalid output path: {e}") from e
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
        if path:
            try:
                target = _sanitize_path(path)
            except ValueError as e:
                self._json({"error": str(e)}, 403)
                return
        else:
            target = _PROJECT_ROOT
        
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

def _setup_https_context() -> ssl.SSLContext | None:
    """Load HTTPS certificate and key from environment variables.
    
    Expects:
    - PROMPT_FORGE_SSL_CERT: path to certificate file (PEM format)
    - PROMPT_FORGE_SSL_KEY: path to key file (PEM format)
    
    Returns None if not configured (HTTP-only mode).
    """
    cert_path = os.environ.get("PROMPT_FORGE_SSL_CERT")
    key_path = os.environ.get("PROMPT_FORGE_SSL_KEY")
    
    if not cert_path or not key_path:
        return None
    
    try:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cert_path, keyfile=key_path)
        return context
    except FileNotFoundError as e:
        log.warning("SSL certificate/key not found, falling back to HTTP: %s", e)
        return None
    except ssl.SSLError as e:
        log.warning("Failed to load SSL certificates, falling back to HTTP: %s", e)
        return None


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    if not _UI_DIR.exists():
        log.error("UI assets missing: %s", _UI_DIR)
        return 2
    
    # Setup HTTPS if certificates are configured
    ssl_context = _setup_https_context()
    protocol = "https" if ssl_context else "http"
    
    httpd = ThreadingHTTPServer((host, port), _Handler)
    if ssl_context:
        httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)
    
    # When the user binds to a wildcard, the bind address (0.0.0.0 / ::) is
    # not a usable URL for a browser, so derive a clickable URL using the
    # machine's hostname and warn that there is no authentication.
    listen_url = f"{protocol}://{host}:{port}/"
    if host in ("0.0.0.0", "::", ""):
        try:
            display_host = socket.gethostname()
        except Exception:  # noqa: BLE001
            display_host = "localhost"
        clickable_url = f"{protocol}://{display_host}:{port}/"
        api_key_msg = " with API key authentication" if _get_api_key() else " with NO authentication"
        log.warning(
            "prompt_forge UI is binding to %s%s — anyone "
            "who can reach this machine on the network can drive the UI and "
            "trigger subprocesses. Only do this on a trusted network.", host, api_key_msg,
        )
        print(
            f"prompt_forge UI listening on {listen_url} (open: {clickable_url})",
            file=sys.stderr,
        )
        print(
            f"WARNING: bound to a non-loopback address{api_key_msg}. "
            "Only expose this on networks you trust.",
            file=sys.stderr,
        )
    else:
        clickable_url = listen_url
        log.info("prompt_forge UI listening on %s", listen_url)
        print(f"prompt_forge UI listening on {listen_url}", file=sys.stderr)
    print(f"config.json: {_CONFIG_PATH}", file=sys.stderr)
    if open_browser:
        try:
            webbrowser.open(clickable_url)
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
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Bind address (default: 127.0.0.1, loopback only). "
            "Pass 0.0.0.0 to listen on every interface so other machines on "
            "the LAN can connect, or a specific NIC IP to restrict to one "
            "interface. Note: there is no authentication; only expose this "
            "on a trusted network."
        ),
    )
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
    # Apply secrets filter to all loggers to prevent credential leakage
    logging.getLogger().addFilter(_SecretsFilter())
    return serve(args.host, args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
