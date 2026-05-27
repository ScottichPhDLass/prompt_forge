"""End-to-end smoke test against a stub Ollama / LM Studio HTTP server.

Verifies, for both providers (Ollama-shaped and OpenAI-compatible) and both
targets (FLUX and SDXL):

- POST /api/chat or /v1/chat/completions is wired correctly
- Per-prompt rewriter, boilerplate extractor, and stripper templates wire
- Checkpointing creates files under the cache dir
- Output structure preserves model_name/display_name/description/sets order
- Validation runs (we deliberately give it valid synthetic outputs)
- For SDXL: output prompts are structured objects with positive_tags etc.
- For FLUX: output prompts are [pos, neg] strings, opening template enforced
- Resume: re-running with the same args is a no-op
"""
from __future__ import annotations

import http.server
import json
import shutil
import socket
import sys
import tempfile
import threading
from pathlib import Path

# Make the package importable when run as a script.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from prompt_forge.cli import main as cli_main  # noqa: E402


# ---------------------------------------------------------------------------
# Fake LLM server (handles both providers and both targets)
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    # Quiet logs.
    def log_message(self, format, *args):  # noqa: A003
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/api/tags":
            self._send_json({"models": [{"name": "fake-model"}]})
        elif self.path == "/v1/models":
            self._send_json({"data": [{"id": "fake-model"}]})
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        if self.path not in ("/api/chat", "/v1/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        msgs = body.get("messages", [])
        sys_msg = msgs[0]["content"] if msgs else ""
        user_msg = msgs[1]["content"] if len(msgs) > 1 else ""

        is_sdxl = "SDXL" in sys_msg

        if "Decision policy (hybrid mode)" in sys_msg:
            content = self._fake_sdxl_per_prompt() if is_sdxl else self._fake_flux_per_prompt()
        elif "distilling the common style fingerprint" in sys_msg.lower():
            content = self._fake_sdxl_extract() if is_sdxl else self._fake_flux_extract()
        elif "removing duplicated boilerplate" in sys_msg.lower():
            content = self._fake_sdxl_strip() if is_sdxl else self._fake_flux_strip()
        else:
            content = json.dumps({"error": "unknown template"})

        if self.path == "/api/chat":
            self._send_json({"message": {"content": content}})
        else:
            self._send_json({
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
            })

    # ---- FLUX fakes ----------------------------------------------------

    def _fake_flux_per_prompt(self) -> str:
        return json.dumps({
            "decision": "rewrite",
            "shot_type": "medium shot",
            "positive": (
                "realistic photographic medium shot of a detective in a rainy back alley, "
                "the camera at chest height looking slightly upward at the figure, "
                "single hard key light from a swinging streetlamp casting a long crisp shadow "
                "across the wet asphalt while a softer fill from a nearby diner sign lifts the "
                "shadow side just enough to retain detail in the trench coat fabric, weave of "
                "the wool overcoat clearly visible alongside subtle skin pores, individual "
                "stubble strands, fogged breath, scuffs in the asphalt, oil-slick reflections, "
                "high contrast yet natural with preserved highlight rolloff and deep shadow "
                "detail across the entire scene."
            ),
            "negative": (
                "noise, film grain, analog noise, dithering, pointillism, grit, dust, "
                "scratches overlays, low quality, low resolution, jpeg artifacts, "
                "chromatic aberration around streetlamp halos, watercolor, oil painting, "
                "illustration, anime, cartoon, comic look, vector art, 3d render, octane "
                "render, cgsociety, beauty filter, plastic skin, waxy skin, doll-like, "
                "global gaussian blur, flat even lighting with no shadow pattern, "
                "crushed blacks erasing alley texture, blown-out highlights washing out "
                "shadow edges, visible text, logos, watermarks"
            ),
        })

    def _fake_flux_extract(self) -> str:
        return json.dumps({
            "positive_boilerplate": (
                "color photography, high contrast yet natural, preserved highlight rolloff, "
                "deep shadow detail, distinct skin pores, fine fabric weave"
            ),
            "negative_boilerplate": (
                "noise, film grain, analog noise, dithering, pointillism, grit, dust, "
                "scratches overlays, low quality, low resolution, jpeg artifacts, "
                "watercolor, illustration, anime, cartoon, vector art, 3d render, "
                "octane render, cgsociety, beauty filter, plastic skin, global gaussian "
                "blur, visible text, logos, watermarks"
            ),
        })

    def _fake_flux_strip(self) -> str:
        return json.dumps({
            "positive": (
                "realistic photographic medium shot of a detective in a rainy back alley, "
                "the camera at chest height looking slightly upward at the figure, "
                "single hard key light from a swinging streetlamp casting a long crisp shadow "
                "across wet asphalt, fogged breath and oil-slick reflections, individual "
                "stubble strands and trench coat folds visible in the fill from a nearby diner sign."
            ),
            "negative": (
                "chromatic aberration around streetlamp halos, flat even lighting with no "
                "shadow pattern, crushed blacks erasing alley texture, blown-out highlights "
                "washing out shadow edges, doll-like, oil painting, comic look"
            ),
        })

    # ---- SDXL fakes ----------------------------------------------------

    def _fake_sdxl_per_prompt(self) -> str:
        return json.dumps({
            "decision": "rewrite",
            "shot_type": "medium shot",
            "positive_tags": [
                "realistic photograph", "medium shot", "a detective",
                "trench coat", "wet asphalt", "rainy back alley",
                "chiaroscuro lighting", "swinging streetlamp", "rim light",
                "fogged breath", "visible skin pores", "fabric weave",
                "high contrast yet natural", "film noir mood",
                "masterpiece", "best quality", "highly detailed",
            ],
            "negative_tags": [
                "3d render", "octane render", "cgi", "cgsociety",
                "illustration", "painting", "drawing", "anime", "cartoon",
                "comic", "vector art", "concept art",
                "blurry", "out of focus", "motion blur", "gaussian blur",
                "low quality", "lowres", "worst quality", "jpeg artifacts",
                "deformed", "bad anatomy", "bad hands", "extra fingers",
                "watermark", "signature", "text", "logo",
                "plastic skin", "waxy skin", "airbrushed", "smooth skin",
                "doll-like", "beauty filter", "monochrome", "black and white",
            ],
            "weights": {"chiaroscuro lighting": 1.2, "swinging streetlamp": 1.1},
            "breaks": [6, 12],
        })

    def _fake_sdxl_extract(self) -> str:
        return json.dumps({
            "positive_boilerplate_tags": [
                "color photography", "realistic photograph",
                "high contrast yet natural", "visible skin pores",
                "fabric weave", "masterpiece", "best quality",
                "highly detailed", "sharp focus",
            ],
            "negative_boilerplate_tags": [
                "3d render", "octane render", "cgi", "illustration",
                "anime", "cartoon", "vector art", "blurry", "motion blur",
                "low quality", "lowres", "jpeg artifacts", "deformed",
                "bad anatomy", "watermark", "text", "logo", "plastic skin",
                "smooth skin", "monochrome", "black and white",
            ],
        })

    def _fake_sdxl_strip(self) -> str:
        # Simulate the stripper trimming boilerplate-overlapping tags
        # ("realistic photograph", "high contrast yet natural", quality tags)
        # and leaving the scene-specific ones intact.
        return json.dumps({
            "positive_tags": [
                "medium shot", "a detective", "trench coat",
                "wet asphalt", "rainy back alley",
                "chiaroscuro lighting", "swinging streetlamp", "rim light",
                "fogged breath", "film noir mood",
            ],
            "negative_tags": [
                "chromatic aberration", "flat even lighting",
                "crushed blacks", "blown highlights",
            ],
            "weights": {"chiaroscuro lighting": 1.2, "swinging streetlamp": 1.1},
            "breaks": [5],
        })

    # ---- helpers -------------------------------------------------------

    def _send_json(self, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _start_fake_server() -> tuple[http.server.HTTPServer, str]:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

SAMPLE_INPUT = {
    "decks": [
        {
            "model_name": "TestModel",
            "display_name": "Test Deck",
            "description": "A test deck.",
            "sets": [
                {
                    "name": "Test Set",
                    "abbr": "TestSet",
                    "description": "A test set.",
                    "boilerplate": {"positive": "old positive bp", "negative": "old negative bp"},
                    "prompts": [
                        ["a detective in a rainy alley", "modern look"],
                        "a single narrative-style prompt as bare string",
                        ["a stadium crowd seen from above forming a spiral", "sparse scene"],
                    ],
                },
                {
                    "name": "Untouched Set",
                    "abbr": "Skip",
                    "description": "Should pass through unchanged.",
                    "boilerplate": {"positive": "keep me", "negative": "keep me too"},
                    "prompts": [["x", "y"]],
                },
            ],
        }
    ]
}


def _run_flux(provider: str) -> None:
    httpd, host = _start_fake_server()
    try:
        with tempfile.TemporaryDirectory() as td:
            in_path = Path(td) / "in.json"
            out_path = Path(td) / "out.json"
            ckpt_dir = Path(td) / "ckpt"
            in_path.write_text(json.dumps(SAMPLE_INPUT), "utf-8")

            argv = [
                "-i", str(in_path),
                "-o", str(out_path),
                "--target", "flux",
                "--deck", "Test Deck",
                "--set", "Test Set",
                "--provider", provider,
                "--host", host,
                "--model", "fake-model",
                "--checkpoint-dir", str(ckpt_dir),
                "--concurrency", "1",
                "-v",
            ]
            rc = cli_main(argv)
            assert rc == 0, f"CLI exit {rc}"

            out = json.loads(out_path.read_text("utf-8"))
            assert out.get("target") == "flux"
            deck = out["decks"][0]
            assert deck["model_name"] == "TestModel"
            assert len(deck["sets"]) == 2

            target = deck["sets"][0]
            untouched = deck["sets"][1]

            assert isinstance(target["prompts"], list) and len(target["prompts"]) == 3
            for pair in target["prompts"]:
                assert isinstance(pair, list) and len(pair) == 2
                pos, neg = pair
                assert pos.lower().startswith("realistic photographic"), pos[:80]
                assert "monochrome" not in pos.lower()
                assert "," in neg
            assert target["boilerplate"]["positive"].startswith("color photography")

            assert untouched["boilerplate"]["positive"] == "keep me"
            assert untouched["prompts"] == [["x", "y"]]

            # checkpoint exists and is target-stamped
            ckpt_file = ckpt_dir / "deck00_set00.json"
            assert ckpt_file.exists()
            ckpt = json.loads(ckpt_file.read_text("utf-8"))
            assert ckpt["completed"] is True
            assert ckpt["target"] == "flux"

            # Resume: should be a no-op
            rc2 = cli_main(argv)
            assert rc2 == 0

            shutil.rmtree(ckpt_dir, ignore_errors=True)

        print(f"  FLUX smoke test passed (provider={provider})")
    finally:
        httpd.shutdown()


def _run_sdxl(provider: str) -> None:
    httpd, host = _start_fake_server()
    try:
        with tempfile.TemporaryDirectory() as td:
            in_path = Path(td) / "in.json"
            ckpt_dir = Path(td) / "ckpt"
            in_path.write_text(json.dumps(SAMPLE_INPUT), "utf-8")

            # Don't pass -o so we exercise the default '<input_stem>.sdxl.json' path.
            argv = [
                "-i", str(in_path),
                "--target", "sdxl",
                "--deck", "Test Deck",
                "--set", "Test Set",
                "--provider", provider,
                "--host", host,
                "--model", "fake-model",
                "--checkpoint-dir", str(ckpt_dir),
                "--concurrency", "1",
                "-v",
            ]
            rc = cli_main(argv)
            assert rc == 0, f"CLI exit {rc}"

            expected_out = in_path.with_name(f"{in_path.stem}.sdxl.json")
            assert expected_out.exists(), f"expected default SDXL output at {expected_out}"
            out = json.loads(expected_out.read_text("utf-8"))
            assert out.get("target") == "sdxl"

            deck = out["decks"][0]
            target = deck["sets"][0]
            untouched = deck["sets"][1]

            # Each prompt is now a structured object.
            assert isinstance(target["prompts"], list) and len(target["prompts"]) == 3
            for entry in target["prompts"]:
                assert isinstance(entry, dict)
                assert isinstance(entry["positive_tags"], list) and entry["positive_tags"]
                assert isinstance(entry["negative_tags"], list) and entry["negative_tags"]
                # No monochrome leak in positives
                assert not any(
                    "monochrome" in t.lower() or "black and white" in t.lower()
                    for t in entry["positive_tags"]
                )
                # weights and breaks fields are present (may be empty)
                assert "weights" in entry and isinstance(entry["weights"], dict)
                assert "breaks" in entry and isinstance(entry["breaks"], list)
                # All break indexes valid
                for b in entry["breaks"]:
                    assert 0 < int(b) < len(entry["positive_tags"])

            # Boilerplate is now tag-list shaped.
            bp = target["boilerplate"]
            assert isinstance(bp.get("positive_tags"), list) and bp["positive_tags"]
            assert isinstance(bp.get("negative_tags"), list) and bp["negative_tags"]
            assert "color photography" in bp["positive_tags"]

            # Untouched set should still pass through with its original boilerplate.
            assert untouched["boilerplate"]["positive"] == "keep me"
            assert untouched["prompts"] == [["x", "y"]]

            # Checkpoint stamped sdxl
            ckpt_file = ckpt_dir / "deck00_set00.json"
            assert ckpt_file.exists()
            ckpt = json.loads(ckpt_file.read_text("utf-8"))
            assert ckpt["completed"] is True
            assert ckpt["target"] == "sdxl"
            assert isinstance(ckpt["prompts"][0], dict)

            # Resume is a no-op
            rc2 = cli_main(argv)
            assert rc2 == 0

            # Verify cross-target checkpoint protection: switching to FLUX
            # against the same checkpoint dir should fail loudly.
            argv_flux = list(argv)
            i = argv_flux.index("--target")
            argv_flux[i + 1] = "flux"
            argv_flux.extend(["-o", str(Path(td) / "should_not_be_written.json")])
            try:
                rc3 = cli_main(argv_flux)
            except RuntimeError as e:
                assert "target=" in str(e), f"unexpected RuntimeError: {e}"
            else:
                # The pipeline raises RuntimeError; the CLI doesn't currently
                # catch it, so getting here would mean it silently succeeded.
                assert rc3 != 0, "expected a non-zero exit when targets mismatch"

            shutil.rmtree(ckpt_dir, ignore_errors=True)

        print(f"  SDXL smoke test passed (provider={provider})")
    finally:
        httpd.shutdown()


def main() -> int:
    for provider in ("ollama", "lmstudio"):
        print(f"\n[{provider}]")
        _run_flux(provider)
        _run_sdxl(provider)
    print("\nALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
