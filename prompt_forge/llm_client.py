"""LLM provider abstraction.

Five concrete providers are supported:

- **Ollama** at ``http://host:11434/api/chat`` (Ollama-native shape, ``format=json``)
- **LM Studio** at ``http://host:1234/v1/chat/completions`` (OpenAI-compatible
  shape, ``response_format={"type":"json_object"}``)
- **Gemini** at ``https://generativelanguage.googleapis.com/v1beta/openai/``
  (OpenAI-compatible, requires a real Google AI Studio API key)
- **DeepSeek** at ``https://api.deepseek.com`` (OpenAI-compatible,
  requires a real DeepSeek API key)
- **openai** (generic OpenAI-compatible) at any custom ``host`` URL.

All expose the same surface to the rest of the pipeline:

    client.ping() -> bool
    client.list_models() -> list[str]
    client.chat_json(system, user, *, schema_hint=None, extra_options=None) -> dict

The ``chat_json`` contract is identical: send a system + user message, get back
a parsed JSON object. Provider-specific quirks (timeout retries, thinking-block
truncation, OpenAI-style choices array) are handled inside each implementation.

Stdlib only — no new dependencies.
"""
from __future__ import annotations

import abc
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class LLMError(RuntimeError):
    """Raised for any provider-side failure that the pipeline should handle."""


# Backwards-compatible alias so existing code (and tests) that import
# OllamaError keep working.
OllamaError = LLMError


@dataclass
class LLMConfig:
    """Shared config for any provider.

    The same dataclass is used for both Ollama and LM Studio. ``provider``
    selects the implementation; ``api_key`` is only used by LM Studio (which
    accepts an arbitrary string when its built-in OpenAI server is enabled).
    """

    provider: str = "auto"            # "ollama" | "lmstudio" | "gemini" | "deepseek" | "openai" | "auto"
    host: str = ""                    # e.g. "http://127.0.0.1:11434"
    model: str = ""
    timeout_s: int = 240
    temperature: float = 0.4
    top_p: float = 0.9
    num_predict: int = 1200           # maps to max_tokens for LM Studio
    max_retries: int = 3
    api_key: str = "lm-studio"        # LM Studio ignores the value but requires the header
    # LM Studio / OpenAI reasoning-model knob. "low" | "medium" | "high" | "".
    # Empty string means "don't send the field" (server uses its own default).
    # Reasoning models like Nemotron-3-Super, DeepSeek-R1, QwQ honor this and
    # it dramatically reduces the share of max_tokens consumed by hidden
    # reasoning, leaving room for visible content.
    reasoning_effort: str = ""

    # Model context window in tokens. Used by the boilerplate extractor to
    # size its prompt sample so it doesn't exceed the model's n_ctx.
    # Default 8192 matches LM Studio's default context for most models.
    context_length: int = 8192

    # Default hosts / base URLs per provider, used when ``host`` is empty.
    default_hosts: dict[str, str] = field(
        default_factory=lambda: {
            "ollama": "http://127.0.0.1:11434",
            "lmstudio": "http://127.0.0.1:1234",
            "lm_studio": "http://127.0.0.1:1234",
            "lm-studio": "http://127.0.0.1:1234",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
            "deepseek": "https://api.deepseek.com",
            "openai": "",  # user must supply host URL for generic OpenAI-compatible endpoints
        }
    )


# Backwards-compatible alias.
OllamaConfig = LLMConfig


class LLMClient(Protocol):
    """Minimal interface every provider implementation must satisfy."""

    cfg: LLMConfig

    def ping(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


# A custom User-Agent is required because some hosted reverse proxies
# (notably Runpod's https://*.proxy.runpod.net edge) return 403 Forbidden
# to the default ``Python-urllib/3.x`` UA. Any non-default UA is accepted.
try:
    from . import __version__ as _PKG_VERSION  # type: ignore
except Exception:  # pragma: no cover - defensive fallback
    _PKG_VERSION = "0"
_DEFAULT_UA = f"prompt_forge/{_PKG_VERSION}"


def _with_default_ua(headers: dict | None) -> dict:
    """Return a header dict that always carries our User-Agent.

    Caller-supplied User-Agent values win, so users can override via
    ``LLMConfig.api_key`` / future header hooks if a deployment needs it.
    """
    out: dict[str, str] = {"User-Agent": _DEFAULT_UA}
    if headers:
        out.update(headers)
    return out


def _post_json(url: str, body: dict, *, timeout: int, headers: dict | None = None) -> dict:
    """POST a JSON body and return the parsed JSON response.

    Raises LLMError on HTTP errors, urllib.error.URLError / TimeoutError on
    transport problems (so callers can distinguish timeout vs other errors).
    """
    data = json.dumps(body).encode("utf-8")
    hdrs = _with_default_ua({"Content-Type": "application/json"})
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise LLMError(f"HTTP {e.code} from {url}: {err_body[:400]}") from e
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        raise LLMError(f"Non-JSON response from {url}: {payload[:300]}") from e


def _get_json(url: str, *, timeout: int, headers: dict | None = None) -> dict:
    hdrs = _with_default_ua(headers)
    req = urllib.request.Request(url, method="GET", headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_json_loose(text: str) -> dict[str, Any]:
    """Parse JSON, tolerating leading/trailing prose or code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    return json.loads(text[start : end + 1])


def _retry_loop(cfg: LLMConfig, fn):
    """Run ``fn`` with retries on JSON parse / LLMError, but NOT on timeouts.

    Timeouts are surfaced immediately because the model is still running on
    the server and retrying just stacks more requests behind the in-flight
    one.
    """
    last_err: Exception | None = None
    for attempt in range(1, cfg.max_retries + 1):
        try:
            return fn(attempt)
        except (urllib.error.URLError, TimeoutError) as e:
            inner = getattr(e, "reason", e)
            if isinstance(inner, TimeoutError) or isinstance(e, TimeoutError):
                raise LLMError(
                    f"Request timed out after {cfg.timeout_s}s. The model is "
                    f"likely still generating on the server. Increase "
                    f"timeout_s in your config (try 600+ for the boilerplate-"
                    f"extractor pass on small/slow models)."
                ) from e
            last_err = e
            time.sleep(min(2 ** attempt, 30))
        except (LLMError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(min(2 ** attempt, 30))
    raise LLMError(f"chat_json failed after {cfg.max_retries} attempts: {last_err!r}")


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------


class OllamaClient:
    """Talks to Ollama's native ``/api/chat`` endpoint with ``format=json``."""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    # ---- discovery ------------------------------------------------------

    def ping(self) -> bool:
        try:
            _get_json(f"{self.cfg.host.rstrip('/')}/api/tags", timeout=10)
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            data = _get_json(f"{self.cfg.host.rstrip('/')}/api/tags", timeout=15)
        except Exception:
            return []
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    # ---- main entry point ----------------------------------------------

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_user = user
        if schema_hint:
            prompt_user = f"{user}\n\nReturn ONLY a JSON object matching this schema:\n{schema_hint}"

        def _attempt(_attempt_idx: int) -> dict[str, Any]:
            raw = self._chat_raw(system, prompt_user, extra_options=extra_options)
            msg = raw.get("message", {}) or {}
            content = msg.get("content", "") or ""
            if not content:
                thinking = msg.get("thinking", "") or ""
                done_reason = raw.get("done_reason", "")
                eval_count = raw.get("eval_count", 0)
                if thinking and done_reason == "length":
                    raise LLMError(
                        f"Reasoning model '{self.cfg.model}' exhausted num_predict "
                        f"({self.cfg.num_predict}) inside its `thinking` block "
                        f"before producing visible content. Increase num_predict "
                        f"to 4096+ or use a non-reasoning model. Thinking preview: "
                        f"{thinking.strip()[:160]!r}"
                    )
                if done_reason == "load":
                    raise LLMError(
                        "Model returned only its load event with no generation; retrying."
                    )
                if eval_count == 0:
                    raise LLMError(
                        f"Model '{self.cfg.model}' produced zero output tokens "
                        f"(likely chat-template or stop-token mismatch)."
                    )
                raise LLMError(
                    f"Empty content from Ollama (done_reason={done_reason!r})."
                )
            return _parse_json_loose(content)

        return _retry_loop(self.cfg, _attempt)

    # ---- internal -------------------------------------------------------

    def _chat_raw(
        self,
        system: str,
        user: str,
        *,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "num_predict": self.cfg.num_predict,
        }
        if extra_options:
            options.update(extra_options)
        body = {
            "model": self.cfg.model,
            "stream": False,
            "format": "json",
            "options": options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        return _post_json(
            f"{self.cfg.host.rstrip('/')}/api/chat",
            body,
            timeout=self.cfg.timeout_s,
        )


# ---------------------------------------------------------------------------
# LM Studio provider
# ---------------------------------------------------------------------------


class LMStudioClient:
    """Talks to LM Studio via its OpenAI-compatible ``/v1/chat/completions``.

    LM Studio ships with an "OpenAI-like server" toggle that exposes the same
    routes as ``api.openai.com``. We use:

    - ``GET /v1/models`` for discovery
    - ``POST /v1/chat/completions`` with ``response_format={"type":"json_object"}``
      for JSON-mode chat

    Note: at ``/v1/chat/completions`` the response shape is the OpenAI one:
    ``{"choices":[{"message":{"content": "..."}}]}``, NOT Ollama's
    ``{"message":{"content":"..."}}``.
    """

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    # ---- discovery ------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        # LM Studio doesn't validate the key, but it does require the header
        # for OpenAI-client compatibility.
        return {"Authorization": f"Bearer {self.cfg.api_key or 'lm-studio'}"}

    def ping(self) -> bool:
        try:
            _get_json(
                f"{self.cfg.host.rstrip('/')}/v1/models",
                timeout=10,
                headers=self._auth_headers(),
            )
            return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMError(
                    f"Authentication failed (HTTP {e.code}) at {self.cfg.host}. "
                    f"Check the API key in the LLM Provider settings."
                ) from e
            raise LLMError(
                f"Server returned HTTP {e.code} at {self.cfg.host}. "
                f"Is the LM Studio server running?"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(
                f"Cannot reach {self.cfg.host}. "
                f"Is the LM Studio server running and accessible?"
            ) from e

    def list_models(self) -> list[str]:
        try:
            data = _get_json(
                f"{self.cfg.host.rstrip('/')}/v1/models",
                timeout=15,
                headers=self._auth_headers(),
            )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMError(
                    f"Authentication failed (HTTP {e.code}) at {self.cfg.host}. "
                    f"Check the API key in the LLM Provider settings."
                ) from e
            raise LLMError(
                f"Server returned HTTP {e.code} at {self.cfg.host}. "
                f"Is the LM Studio server running?"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(
                f"Cannot reach {self.cfg.host}. "
                f"Is the LM Studio server running and accessible?"
            ) from e
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    # ---- main entry point ----------------------------------------------

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_user = user
        if schema_hint:
            prompt_user = f"{user}\n\nReturn ONLY a JSON object matching this schema:\n{schema_hint}"

        # Build a real json_schema when the caller gave us one. LM Studio
        # constrains output to this schema, which is far more reliable than
        # the prose hint alone. We translate the loose schema_hint string
        # into a permissive JSON Schema; if that fails we fall back to text.
        response_format = _schema_hint_to_response_format(schema_hint)

        def _attempt(_attempt_idx: int) -> dict[str, Any]:
            raw = self._chat_raw(
                system,
                prompt_user,
                extra_options=extra_options,
                response_format=response_format,
            )
            choices = raw.get("choices") or []
            if not choices:
                err = raw.get("error", {}) or {}
                if err:
                    raise LLMError(f"LM Studio error: {err.get('message') or err}")
                raise LLMError(f"LM Studio returned no choices: {str(raw)[:300]}")

            choice = choices[0]
            finish = choice.get("finish_reason", "")
            msg = choice.get("message", {}) or {}
            content = msg.get("content", "") or ""
            
            # Some reasoning models put the visible output in reasoning_content
            # and leave content empty. Fall back gracefully.
            if not content.strip():
                rc = msg.get("reasoning_content", "") or ""
                if rc.strip():
                    content = rc

            if not content.strip():
                # Surface usage info when present so users can see what happened.
                usage = raw.get("usage", {}) or {}
                details = usage.get("completion_tokens_details") or {}
                reasoning_tokens = details.get("reasoning_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                # Reasoning model burned the budget on hidden tokens.
                if reasoning_tokens and reasoning_tokens >= max(1, completion_tokens - 4):
                    effort_hint = (
                        f" Currently reasoning_effort={self.cfg.reasoning_effort!r}."
                        if self.cfg.reasoning_effort
                        else " reasoning_effort is unset (server default)."
                    )
                    raise LLMError(
                        f"Reasoning model '{self.cfg.model}' spent {reasoning_tokens} of "
                        f"{completion_tokens} completion tokens on hidden reasoning, "
                        f"leaving no room for visible content.{effort_hint} "
                        f"Fixes: set [llm].reasoning_effort = \"low\" in your config, "
                        f"and/or raise [llm].num_predict to 4096+."
                    )
                if finish == "length":
                    raise LLMError(
                        f"Model '{self.cfg.model}' hit max_tokens "
                        f"({self.cfg.num_predict}) before producing content. "
                        f"Increase num_predict in your config. usage={usage}"
                    )
                raise LLMError(
                    f"Empty content from LM Studio (finish_reason={finish!r}, usage={usage})."
                )
            return _parse_json_loose(content)

        return _retry_loop(self.cfg, _attempt)

    # ---- internal -------------------------------------------------------

    def _chat_raw(
        self,
        system: str,
        user: str,
        *,
        extra_options: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "stream": False,
            "temperature": self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "max_tokens": self.cfg.num_predict,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # Pass reasoning_effort through when configured. LM Studio + Ollama
        # both surface this OpenAI-style knob for reasoning models. Only send
        # the field when explicitly set to avoid breaking models that don't
        # recognize it.
        if self.cfg.reasoning_effort:
            body["reasoning_effort"] = self.cfg.reasoning_effort
        # LM Studio's OpenAI-compatible server only accepts response_format of
        # type "json_schema" or "text" (it rejects "json_object" with HTTP 400).
        # Default to "text" and let the system prompt enforce JSON; chat_json()
        # passes a real json_schema when it has one.
        body["response_format"] = response_format or {"type": "text"}
        if extra_options:
            body.update(extra_options)
        return _post_json(
            f"{self.cfg.host.rstrip('/')}/v1/chat/completions",
            body,
            timeout=self.cfg.timeout_s,
            headers=self._auth_headers(),
        )


# ---------------------------------------------------------------------------
# LM Studio JSON Schema helpers
# ---------------------------------------------------------------------------


def _schema_hint_to_response_format(schema_hint: str | None) -> dict[str, Any]:
    """Convert the human-readable schema_hint into a JSON Schema response_format.

    Our schema hints are simple: an object whose values are either type
    annotations like ``"string"`` / ``"integer"`` or pipe-separated literals
    like ``"rewrite | normalize"``. We map them to a permissive JSON Schema
    so LM Studio constrains output without rejecting valid completions for
    being one synonym off.

    On any parse failure we return ``{"type": "text"}`` so the system prompt
    alone enforces JSON output.
    """
    if not schema_hint:
        return {"type": "text"}
    try:
        # The hints are JSON-ish but the values are free text. Strip the value
        # side and just keep the keys, then build an object schema where each
        # property is a string. This is permissive enough to never reject a
        # well-formed model response while still enforcing object structure.
        parsed = json.loads(schema_hint)
        if not isinstance(parsed, dict):
            return {"type": "text"}
        properties: dict[str, Any] = {}
        for k in parsed.keys():
            properties[k] = {"type": "string"}
        json_schema = {
            "type": "object",
            "properties": properties,
            # Don't require keys: small models occasionally omit one and we'd
            # rather repair than 400-error mid-pipeline.
            "additionalProperties": True,
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "prompt_forge_response",
                "strict": False,
                "schema": json_schema,
            },
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"type": "text"}


# ---------------------------------------------------------------------------
# Gemini provider (remote API)
# ---------------------------------------------------------------------------


class GeminiClient:
    """Talks to the Gemini API via its OpenAI-compatible ``/v1/chat/completions``.

    Uses ``https://generativelanguage.googleapis.com/v1beta/openai`` by default.
    Requires a real Google AI Studio API key passed as ``api_key``.
    """

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    # ---- discovery ------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.api_key}"}

    def ping(self) -> bool:
        try:
            _get_json(
                f"{self.cfg.host.rstrip('/')}/v1/models",
                timeout=10,
                headers=self._auth_headers(),
            )
            return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMError(
                    f"Authentication failed (HTTP {e.code}) at {self.cfg.host}. "
                    f"Check your Gemini API key."
                ) from e
            raise LLMError(
                f"Server returned HTTP {e.code} at {self.cfg.host}. "
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(
                f"Cannot reach {self.cfg.host}. "
                f"Is the network accessible?"
            ) from e

    def list_models(self) -> list[str]:
        try:
            data = _get_json(
                f"{self.cfg.host.rstrip('/')}/v1/models",
                timeout=15,
                headers=self._auth_headers(),
            )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMError(
                    f"Authentication failed (HTTP {e.code}) at {self.cfg.host}. "
                    f"Check your Gemini API key."
                ) from e
            raise LLMError(
                f"Server returned HTTP {e.code} at {self.cfg.host}. "
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(
                f"Cannot reach {self.cfg.host}. "
                f"Is the network accessible?"
            ) from e
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    # ---- main entry point ----------------------------------------------

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_user = user
        if schema_hint:
            prompt_user = f"{user}\n\nReturn ONLY a JSON object matching this schema:\n{schema_hint}"

        response_format = _schema_hint_to_response_format(schema_hint)

        def _attempt(_attempt_idx: int) -> dict[str, Any]:
            raw = self._chat_raw(
                system,
                prompt_user,
                extra_options=extra_options,
                response_format=response_format,
            )
            choices = raw.get("choices") or []
            if not choices:
                err = raw.get("error", {}) or {}
                if err:
                    raise LLMError(f"Gemini error: {err.get('message') or err}")
                raise LLMError(f"Gemini returned no choices: {str(raw)[:300]}")

            choice = choices[0]
            finish = choice.get("finish_reason", "")
            msg = choice.get("message", {}) or {}
            content = msg.get("content", "") or ""

            if not content.strip():
                usage = raw.get("usage", {}) or {}
                if finish == "length":
                    raise LLMError(
                        f"Gemini model '{self.cfg.model}' hit max_tokens "
                        f"({self.cfg.num_predict}) before producing content. "
                        f"Increase num_predict."
                    )
                raise LLMError(
                    f"Empty content from Gemini (finish_reason={finish!r}, usage={usage})."
                )
            return _parse_json_loose(content)

        return _retry_loop(self.cfg, _attempt)

    # ---- internal -------------------------------------------------------

    def _chat_raw(
        self,
        system: str,
        user: str,
        *,
        extra_options: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "stream": False,
            "temperature": self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "max_tokens": self.cfg.num_predict,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        body["response_format"] = response_format or {"type": "text"}
        if extra_options:
            body.update(extra_options)
        return _post_json(
            f"{self.cfg.host.rstrip('/')}/v1/chat/completions",
            body,
            timeout=self.cfg.timeout_s,
            headers=self._auth_headers(),
        )


# ---------------------------------------------------------------------------
# DeepSeek provider (remote API)
# ---------------------------------------------------------------------------


class DeepSeekClient:
    """Talks to the DeepSeek API via its OpenAI-compatible ``/v1/chat/completions``.

    Uses ``https://api.deepseek.com`` by default.
    Requires a real DeepSeek API key passed as ``api_key``.
    """

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    # ---- discovery ------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.api_key}"}

    def ping(self) -> bool:
        try:
            _get_json(
                f"{self.cfg.host.rstrip('/')}/v1/models",
                timeout=10,
                headers=self._auth_headers(),
            )
            return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMError(
                    f"Authentication failed (HTTP {e.code}) at {self.cfg.host}. "
                    f"Check your DeepSeek API key."
                ) from e
            raise LLMError(
                f"Server returned HTTP {e.code} at {self.cfg.host}. "
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(
                f"Cannot reach {self.cfg.host}. "
                f"Is the network accessible?"
            ) from e

    def list_models(self) -> list[str]:
        try:
            data = _get_json(
                f"{self.cfg.host.rstrip('/')}/v1/models",
                timeout=15,
                headers=self._auth_headers(),
            )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMError(
                    f"Authentication failed (HTTP {e.code}) at {self.cfg.host}. "
                    f"Check your DeepSeek API key."
                ) from e
            raise LLMError(
                f"Server returned HTTP {e.code} at {self.cfg.host}. "
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(
                f"Cannot reach {self.cfg.host}. "
                f"Is the network accessible?"
            ) from e
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    # ---- main entry point ----------------------------------------------

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_user = user
        if schema_hint:
            prompt_user = f"{user}\n\nReturn ONLY a JSON object matching this schema:\n{schema_hint}"

        response_format = _schema_hint_to_response_format(schema_hint)

        def _attempt(_attempt_idx: int) -> dict[str, Any]:
            raw = self._chat_raw(
                system,
                prompt_user,
                extra_options=extra_options,
                response_format=response_format,
            )
            choices = raw.get("choices") or []
            if not choices:
                err = raw.get("error", {}) or {}
                if err:
                    raise LLMError(f"DeepSeek error: {err.get('message') or err}")
                raise LLMError(f"DeepSeek returned no choices: {str(raw)[:300]}")

            choice = choices[0]
            finish = choice.get("finish_reason", "")
            msg = choice.get("message", {}) or {}
            content = msg.get("content", "") or ""

            if not content.strip():
                usage = raw.get("usage", {}) or {}
                if finish == "length":
                    raise LLMError(
                        f"DeepSeek model '{self.cfg.model}' hit max_tokens "
                        f"({self.cfg.num_predict}) before producing content. "
                        f"Increase num_predict."
                    )
                raise LLMError(
                    f"Empty content from DeepSeek (finish_reason={finish!r}, usage={usage})."
                )
            return _parse_json_loose(content)

        return _retry_loop(self.cfg, _attempt)

    # ---- internal -------------------------------------------------------

    def _chat_raw(
        self,
        system: str,
        user: str,
        *,
        extra_options: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "stream": False,
            "temperature": self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "max_tokens": self.cfg.num_predict,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        body["response_format"] = response_format or {"type": "text"}
        if extra_options:
            body.update(extra_options)
        return _post_json(
            f"{self.cfg.host.rstrip('/')}/v1/chat/completions",
            body,
            timeout=self.cfg.timeout_s,
            headers=self._auth_headers(),
        )


def _normalize_host(host: str, *, provider: str, default_hosts: dict[str, str]) -> str:
    """Fill in scheme/host/port if the user gave a partial or empty host."""
    if not host:
        url = default_hosts.get(provider, "")
        if url:
            return url.rstrip("/")
        return "http://127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    return host.rstrip("/")


def make_client(cfg: LLMConfig) -> LLMClient:
    """Return the right provider implementation for ``cfg``.

    If ``provider`` is ``"auto"``, probe both well-known local endpoints and
    pick the first one that responds. Ollama is preferred if both are up
    (matches existing single-provider behavior).
    """
    provider = (cfg.provider or "auto").lower()

    if provider == "auto":
        # Try Ollama first, then LM Studio.
        for candidate in ("ollama", "lmstudio"):
            test_cfg = LLMConfig(
                provider=candidate,
                host=_normalize_host(cfg.host, provider=candidate, default_hosts=cfg.default_hosts),
                model=cfg.model,
                timeout_s=min(cfg.timeout_s, 10),
                temperature=cfg.temperature,
                top_p=cfg.top_p,
                num_predict=cfg.num_predict,
                max_retries=1,
                api_key=cfg.api_key,
                default_hosts=cfg.default_hosts,
            )
            client = _build(candidate, test_cfg)
            try:
                available = client.ping()
            except LLMError:
                # Server responded — could be an auth error or a 5xx.
                # Either way the provider is reachable; select it and let
                # the first real call surface the auth error clearly.
                available = True
            if available:
                # Use the resolved host for the real client.
                cfg.provider = candidate
                cfg.host = test_cfg.host
                return _build(candidate, cfg)
        raise LLMError(
            "Auto-detect found neither Ollama (127.0.0.1:11434) nor LM Studio "
            "(127.0.0.1:1234). Start one of them, or set [llm].provider and "
            "[llm].host explicitly in your config."
        )

    cfg.host = _normalize_host(cfg.host, provider=provider, default_hosts=cfg.default_hosts)
    return _build(provider, cfg)


def _build(provider: str, cfg: LLMConfig) -> LLMClient:
    if provider == "ollama":
        return OllamaClient(cfg)
    if provider in ("lmstudio", "lm_studio", "lm-studio"):
        return LMStudioClient(cfg)
    if provider == "gemini":
        return GeminiClient(cfg)
    if provider == "deepseek":
        return DeepSeekClient(cfg)
    if provider == "openai":
        return GeminiClient(cfg)  # Generic OpenAI-compatible uses same class
    raise LLMError(
        f"Unknown provider {provider!r}. "
        f"Use 'ollama', 'lmstudio', 'gemini', 'deepseek', 'openai', or 'auto'."
    )
