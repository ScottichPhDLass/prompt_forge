"""Core pipeline: hybrid rewrite + boilerplate recompute, with checkpointing.

Supports two diffusion targets:

* ``flux`` (default) - long-form prose positive + comma-separated negative,
  stored as ``[positive_str, negative_str]`` pairs.
* ``sdxl`` - structured CLIP-friendly tag objects with weights and BREAK
  chunking, stored as
  ``{"positive_tags": [...], "negative_tags": [...], "weights": {...},
     "breaks": [...], "shot_type": "...", "decision": "..."}``.

The target is selected via :class:`PipelineConfig.target` and routes the
LLM call to the appropriate template bank in :mod:`templates`.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import templates
from .llm_client import LLMClient, LLMError
from .templates import Target, select_templates
from .validator import validate_pair, validate_sdxl_pair

log = logging.getLogger("prompt_forge")


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    checkpoint_dir: str = ".forge_cache"
    recompute_boilerplate: bool = True
    validate: bool = True
    opening_template: str = "realistic photographic {shot_type} of"
    force_full_color: bool = True
    concurrency: int = 2
    target: Target = "flux"
    variant: str = "default"


@dataclass
class RunSelection:
    """What slice of the input file to process."""
    deck: str | None = None        # match by display_name OR model_name (case-insensitive)
    set_name: str | None = None    # match by name OR abbr (case-insensitive)
    process_all: bool = False      # if True, ignore deck/set filters and do every set


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@dataclass
class _SetCheckpoint:
    """One checkpoint per (deck_idx, set_idx). Stored as JSON on disk.

    For ``target == "flux"``, ``prompts`` is a list of ``[pos_str, neg_str]``.
    For ``target == "sdxl"``, ``prompts`` is a list of dicts.
    ``boilerplate`` shape also varies by target.
    """
    deck_idx: int
    set_idx: int
    target: Target = "flux"
    variant: str = "default"
    prompts: list = field(default_factory=list)
    boilerplate: dict | None = None
    completed: bool = False

    def to_dict(self) -> dict:
        return {
            "deck_idx": self.deck_idx,
            "set_idx": self.set_idx,
            "target": self.target,
            "variant": self.variant,
            "prompts": self.prompts,
            "boilerplate": self.boilerplate,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_SetCheckpoint":
        return cls(
            deck_idx=d["deck_idx"],
            set_idx=d["set_idx"],
            target=d.get("target", "flux"),
            variant=d.get("variant", "default"),
            prompts=d.get("prompts", []),
            boilerplate=d.get("boilerplate"),
            completed=d.get("completed", False),
        )


class Pipeline:
    def __init__(self, client: LLMClient, cfg: PipelineConfig, stripper_client: LLMClient | None = None):
        self.client = client
        self.stripper_client = stripper_client
        self.cfg = cfg
        self.bank = select_templates(cfg.target, cfg.variant)
        Path(self.cfg.checkpoint_dir).mkdir(parents=True, exist_ok=True)

    # ---- entry point ------------------------------------------------------

    def run(self, data: dict[str, Any], selection: RunSelection) -> dict[str, Any]:
        decks = data.get("decks", [])
        targets = list(self._iter_targets(decks, selection))
        if not targets:
            raise ValueError(
                "No deck/set matched the selection. Check --deck and --set values."
            )
        log.info("Processing %d set(s) for target=%s.", len(targets), self.cfg.target)
        for deck_idx, set_idx in targets:
            self._process_set(decks, deck_idx, set_idx)
        return data

    # ---- target selection -------------------------------------------------

    def _iter_targets(self, decks: list[dict], sel: RunSelection):
        for di, deck in enumerate(decks):
            if not sel.process_all and sel.deck:
                if not _name_match(sel.deck, deck.get("display_name"), deck.get("model_name")):
                    continue
            for si, st in enumerate(deck.get("sets", [])):
                if not sel.process_all and sel.set_name:
                    if not _name_match(sel.set_name, st.get("name"), st.get("abbr")):
                        continue
                yield di, si

    # ---- per-set work -----------------------------------------------------

    def _process_set(self, decks: list[dict], deck_idx: int, set_idx: int) -> None:
        deck = decks[deck_idx]
        st = deck["sets"][set_idx]
        deck_label = deck.get("display_name") or deck.get("model_name") or f"deck#{deck_idx}"
        set_label = st.get("name") or st.get("abbr") or f"set#{set_idx}"
        log.info("=== %s :: %s (%d prompts) ===", deck_label, set_label, len(st.get("prompts", [])))

        ckpt = self._load_ckpt(deck_idx, set_idx)
        # Refuse to mix targets within one checkpoint dir; force a clean re-run.
        if ckpt.prompts and ckpt.target != self.cfg.target:
            raise RuntimeError(
                f"Checkpoint at {self._ckpt_path(deck_idx, set_idx)} was produced for "
                f"target={ckpt.target!r} but the current run is target={self.cfg.target!r}. "
                f"Delete the checkpoint or use a different --checkpoint-dir."
            )
        ckpt.target = self.cfg.target
        ckpt.variant = self.cfg.variant

        original_prompts = st.get("prompts", [])
        boilerplate = st.get("boilerplate", {}) or {}
        bp_pos, bp_neg = self._extract_existing_boilerplate(boilerplate)

        # --- Phase 1: rewrite each prompt (resumable) ----------------------
        if not ckpt.prompts or len(ckpt.prompts) < len(original_prompts) or any(
            not self._is_prompt_complete(p) for p in ckpt.prompts[: len(original_prompts)]
        ):
            self._phase_rewrite(
                deck=deck,
                st=st,
                deck_label=deck_label,
                set_label=set_label,
                bp_pos=bp_pos,
                bp_neg=bp_neg,
                original_prompts=original_prompts,
                ckpt=ckpt,
                deck_idx=deck_idx,
                set_idx=set_idx,
            )

        # --- Phase 2: recompute boilerplate --------------------------------
        if self.cfg.recompute_boilerplate and ckpt.boilerplate is None:
            log.info("Recomputing boilerplate for %s :: %s", deck_label, set_label)
            ckpt.boilerplate = self._extract_boilerplate(
                deck_label, set_label, st.get("description", ""), ckpt.prompts
            )
            self._save_ckpt(ckpt)

        # --- Phase 3: strip boilerplate from each prompt -------------------
        if self.cfg.recompute_boilerplate and ckpt.boilerplate and not ckpt.completed:
            log.info("Stripping boilerplate from %d prompts", len(ckpt.prompts))
            ckpt.prompts = self._strip_boilerplate_all(ckpt.boilerplate, ckpt.prompts)
            ckpt.completed = True
            self._save_ckpt(ckpt)

        # --- Apply checkpoint to in-memory data ----------------------------
        st["prompts"] = ckpt.prompts
        if ckpt.boilerplate:
            st["boilerplate"] = ckpt.boilerplate

    # ---- target adapters --------------------------------------------------

    def _is_prompt_complete(self, p: Any) -> bool:
        """True if a checkpointed prompt entry is fully populated."""
        if self.cfg.target == "flux":
            return isinstance(p, list) and len(p) == 2 and bool(p[0]) and bool(p[1])
        # sdxl
        return (
            isinstance(p, dict)
            and isinstance(p.get("positive_tags"), list)
            and bool(p["positive_tags"])
            and isinstance(p.get("negative_tags"), list)
            and bool(p["negative_tags"])
        )

    def _empty_prompt_entry(self) -> Any:
        return [] if self.cfg.target == "flux" else {}

    def _extract_existing_boilerplate(self, bp: dict) -> tuple[str, str]:
        """Return (pos, neg) representations suitable for the system prompt.

        For FLUX they are strings as-is; for SDXL we accept either string or
        list and normalize to a comma-separated string for the LLM prompt.
        """
        if self.cfg.target == "flux":
            return (bp.get("positive", "") or "", bp.get("negative", "") or "")
        # sdxl: prefer tag list, fall back to string
        pos_tags = bp.get("positive_tags") or bp.get("positive_boilerplate_tags")
        neg_tags = bp.get("negative_tags") or bp.get("negative_boilerplate_tags")
        if isinstance(pos_tags, list):
            pos_str = ", ".join(str(t) for t in pos_tags)
        else:
            pos_str = str(bp.get("positive", "") or "")
        if isinstance(neg_tags, list):
            neg_str = ", ".join(str(t) for t in neg_tags)
        else:
            neg_str = str(bp.get("negative", "") or "")
        return pos_str, neg_str

    # ---- phase 1: rewrite -------------------------------------------------

    def _phase_rewrite(
        self,
        *,
        deck: dict,
        st: dict,
        deck_label: str,
        set_label: str,
        bp_pos: str,
        bp_neg: str,
        original_prompts: list,
        ckpt: _SetCheckpoint,
        deck_idx: int,
        set_idx: int,
    ) -> None:
        # Pad ckpt.prompts so indexing is safe.
        while len(ckpt.prompts) < len(original_prompts):
            ckpt.prompts.append(self._empty_prompt_entry())

        todo = [i for i, p in enumerate(ckpt.prompts) if not self._is_prompt_complete(p)]
        log.info("Rewriting %d/%d prompts (resuming if applicable)", len(todo), len(original_prompts))

        def _do_one(i: int) -> tuple[int, Any]:
            src = original_prompts[i]
            src_pos, src_neg = _coerce_pair(src)
            entry = self._rewrite_one(
                deck_label=deck_label,
                set_label=set_label,
                set_description=st.get("description", ""),
                bp_pos=bp_pos,
                bp_neg=bp_neg,
                src_pos=src_pos,
                src_neg=src_neg,
            )
            return i, entry

        if self.cfg.concurrency <= 1:
            for i in todo:
                idx, entry = _do_one(i)
                ckpt.prompts[idx] = entry
                self._save_ckpt(ckpt)
                log.info("  [%d/%d] done", idx + 1, len(original_prompts))
        else:
            with cf.ThreadPoolExecutor(max_workers=self.cfg.concurrency) as ex:
                futures = {ex.submit(_do_one, i): i for i in todo}
                for fut in cf.as_completed(futures):
                    idx, entry = fut.result()
                    ckpt.prompts[idx] = entry
                    self._save_ckpt(ckpt)
                    log.info("  [%d/%d] done", idx + 1, len(original_prompts))

    def _rewrite_one(
        self,
        *,
        deck_label: str,
        set_label: str,
        set_description: str,
        bp_pos: str,
        bp_neg: str,
        src_pos: str,
        src_neg: str,
    ) -> Any:
        user = self.bank.per_prompt_user.format(
            deck_display_name=deck_label,
            set_name=set_label,
            set_description=set_description or "",
            boilerplate_pos=bp_pos or "(none)",
            boilerplate_neg=bp_neg or "(none)",
            src_pos=src_pos,
            src_neg=src_neg,
        )
        out = self.client.chat_json(
            self.bank.per_prompt_system,
            user,
            schema_hint=self.bank.per_prompt_schema,
        )

        if self.cfg.target == "flux":
            return self._post_rewrite_flux(out, user)
        return self._post_rewrite_sdxl(out, user)

    def _post_rewrite_flux(self, out: dict, user_prompt: str) -> list[str]:
        pos = (out.get("positive") or "").strip()
        neg = (out.get("negative") or "").strip()

        if self.cfg.validate:
            res = validate_pair(pos, neg)
            if not res.ok:
                log.warning("Validation issues, attempting one repair pass: %s", res.issues)
                pos2, neg2 = self._repair_flux(user_prompt, res.issues)
                if pos2 is not None:
                    res2 = validate_pair(pos2, neg2)
                    if res2.ok or len(res2.issues) < len(res.issues):
                        pos, neg = pos2, neg2
        return [pos, neg]

    def _repair_flux(self, user_prompt: str, issues: list[str]) -> tuple[str | None, str | None]:
        repair_user = (
            user_prompt
            + "\n\nYour previous attempt had these issues, fix all of them:\n- "
            + "\n- ".join(issues)
            + "\n\nReturn the same JSON shape."
        )
        try:
            out2 = self.client.chat_json(
                self.bank.per_prompt_system,
                repair_user,
                schema_hint=self.bank.per_prompt_schema,
            )
            return (
                (out2.get("positive") or "").strip(),
                (out2.get("negative") or "").strip(),
            )
        except LLMError as e:
            log.warning("Repair pass failed: %s", e)
            return None, None

    def _post_rewrite_sdxl(self, out: dict, user_prompt: str) -> dict:
        entry = _coerce_sdxl_entry(out)
        if self.cfg.validate:
            res = validate_sdxl_pair(entry)
            if not res.ok:
                log.warning("Validation issues, attempting one repair pass: %s", res.issues)
                entry2 = self._repair_sdxl(user_prompt, res.issues)
                if entry2 is not None:
                    res2 = validate_sdxl_pair(entry2)
                    if res2.ok or len(res2.issues) < len(res.issues):
                        entry = entry2
        return entry

    def _repair_sdxl(self, user_prompt: str, issues: list[str]) -> dict | None:
        repair_user = (
            user_prompt
            + "\n\nYour previous attempt had these issues, fix all of them:\n- "
            + "\n- ".join(issues)
            + "\n\nReturn the same JSON shape."
        )
        try:
            out2 = self.client.chat_json(
                self.bank.per_prompt_system,
                repair_user,
                schema_hint=self.bank.per_prompt_schema,
            )
            return _coerce_sdxl_entry(out2)
        except LLMError as e:
            log.warning("Repair pass failed: %s", e)
            return None

    # ---- phase 2: extract boilerplate -------------------------------------

    def _extract_boilerplate(
        self,
        deck_label: str,
        set_label: str,
        set_description: str,
        rewritten: list,
    ) -> dict:
        # Determine how many prompts fit in the model's context window.
        # We budget the full context minus: system prompt, schema hint,
        # user template overhead (without prompts_json), and an output
        # buffer of 512 tokens for the boilerplate response.
        ctx = self.client.cfg.context_length
        # Precompute template overhead by formatting with a minimal placeholder.
        _dummy_json = "[]"
        _overhead_user = self.bank.boilerplate_extractor_user.format(
            deck_display_name=deck_label,
            set_name=set_label,
            set_description=set_description or "",
            prompts_json=_dummy_json,
        )
        _overhead_chars = len(
            self.bank.boilerplate_extractor_system
        ) + len(self.bank.boilerplate_extractor_schema) + len(
            _overhead_user.replace(_dummy_json, "")
        )
        _output_budget = 512  # tokens for the boilerplate response
        _safety_pct = 0.80  # use 80% of calculated budget as safety margin
        _char_budget = int((ctx - _output_budget) * _safety_pct * 4)

        # Walk through evenly-spaced prompts until we hit the budget
        n = len(rewritten)
        sample_size = 0
        stride = max(1, n // 30) if n > 30 else 1  # aim for ~30 entries
        char_cost = _overhead_chars  # starts with fixed overhead
        for idx in range(0, n, stride):
            entry = rewritten[idx]
            if self.cfg.target == "sdxl" and isinstance(entry, dict):
                compact = {
                    "positive_tags": entry.get("positive_tags", []),
                    "negative_tags": entry.get("negative_tags", []),
                }
                entry_str = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(entry, list):
                entry_str = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
            else:
                entry_str = json.dumps(entry, ensure_ascii=False)
            # +2 for comma+newline separator between entries
            char_cost += len(entry_str) + 2
            if char_cost > _char_budget and sample_size >= 5:
                break
            sample_size += 1

        # Re-select the actual sample at the computed size
        sample_idx = list(range(0, n, max(1, n // max(sample_size, 1))))[:max(sample_size, 1)]
        sample = [rewritten[i] for i in sample_idx]
        if self.cfg.target == "sdxl":
            sample = [
                {
                    "positive_tags": e.get("positive_tags", []),
                    "negative_tags": e.get("negative_tags", []),
                }
                for e in sample
                if isinstance(e, dict)
            ]
        user = self.bank.boilerplate_extractor_user.format(
            deck_display_name=deck_label,
            set_name=set_label,
            set_description=set_description or "",
            prompts_json=json.dumps(sample, ensure_ascii=False, separators=(",", ":")),
        )
        log.info(
            "  boilerplate extractor: sending %d/%d prompt entries (%d chars, ctx=%d)",
            len(sample), len(rewritten), len(user), ctx,
        )
        out = self.client.chat_json(
            self.bank.boilerplate_extractor_system,
            user,
            schema_hint=self.bank.boilerplate_extractor_schema,
        )
        if self.cfg.target == "flux":
            return {
                "positive": (out.get("positive_boilerplate") or "").strip(),
                "negative": (out.get("negative_boilerplate") or "").strip(),
            }
        # sdxl
        return {
            "positive_tags": _as_str_list(out.get("positive_boilerplate_tags")),
            "negative_tags": _as_str_list(out.get("negative_boilerplate_tags")),
        }

    # ---- phase 3: strip boilerplate from each prompt ----------------------

    def _strip_boilerplate_all(
        self, boilerplate: dict, prompts: list
    ) -> list:
        if self.cfg.target == "flux":
            bp_pos = boilerplate.get("positive", "")
            bp_neg = boilerplate.get("negative", "")
        else:
            bp_pos = ", ".join(boilerplate.get("positive_tags", []) or [])
            bp_neg = ", ".join(boilerplate.get("negative_tags", []) or [])

        def _do_one_flux(i: int) -> tuple[int, list[str]]:
            pos, neg = prompts[i]
            user = self.bank.boilerplate_stripper_user.format(
                boilerplate_pos=bp_pos or "(none)",
                boilerplate_neg=bp_neg or "(none)",
                pos=pos,
                neg=neg,
            )
            _client = self.stripper_client or self.client
            try:
                out = _client.chat_json(
                    self.bank.boilerplate_stripper_system,
                    user,
                    schema_hint=self.bank.boilerplate_stripper_schema,
                )
                return i, [
                    (out.get("positive") or pos).strip(),
                    (out.get("negative") or neg).strip(),
                ]
            except LLMError as e:
                log.warning("Strip failed for prompt %d, keeping original: %s", i, e)
                return i, [pos, neg]

        def _do_one_sdxl(i: int) -> tuple[int, dict]:
            entry = prompts[i] if isinstance(prompts[i], dict) else {}
            user = self.bank.boilerplate_stripper_user.format(
                boilerplate_pos=bp_pos or "(none)",
                boilerplate_neg=bp_neg or "(none)",
                prompt_json=json.dumps(
                    {
                        "positive_tags": entry.get("positive_tags", []),
                        "negative_tags": entry.get("negative_tags", []),
                        "weights": entry.get("weights", {}),
                        "breaks": entry.get("breaks", []),
                    },
                    ensure_ascii=False,
                ),
            )
            try:
                _client = self.stripper_client or self.client
                out = _client.chat_json(
                    self.bank.boilerplate_stripper_system,
                    user,
                    schema_hint=self.bank.boilerplate_stripper_schema,
                )
                stripped = _coerce_sdxl_entry(out)
                # Preserve fields the stripper doesn't return (decision/shot_type).
                merged = dict(entry)
                merged.update(
                    {
                        "positive_tags": stripped["positive_tags"],
                        "negative_tags": stripped["negative_tags"],
                        "weights": stripped["weights"],
                        "breaks": stripped["breaks"],
                    }
                )
                return i, merged
            except LLMError as e:
                log.warning("Strip failed for prompt %d, keeping original: %s", i, e)
                return i, entry

        total = len(prompts)
        out_list: list[Any] = [None] * total
        worker = _do_one_flux if self.cfg.target == "flux" else _do_one_sdxl
        _log_interval = max(1, total // 10)  # log ~10 ticks for any batch size
        if self.cfg.concurrency <= 1:
            for i in range(total):
                _, entry = worker(i)
                out_list[i] = entry
                if (i + 1) % _log_interval == 0 or i == total - 1:
                    log.info("  strip progress: %d/%d", i + 1, total)
        else:
            done = 0
            with cf.ThreadPoolExecutor(max_workers=self.cfg.concurrency) as ex:
                futures = {ex.submit(worker, i): i for i in range(total)}
                for fut in cf.as_completed(futures):
                    i, entry = fut.result()
                    out_list[i] = entry
                    done += 1
                    if done % _log_interval == 0 or done == total:
                        log.info("  strip progress: %d/%d", done, total)
        return out_list

    # ---- checkpoint I/O ---------------------------------------------------

    def _ckpt_path(self, deck_idx: int, set_idx: int) -> Path:
        return Path(self.cfg.checkpoint_dir) / f"deck{deck_idx:02d}_set{set_idx:02d}.json"

    def _load_ckpt(self, deck_idx: int, set_idx: int) -> _SetCheckpoint:
        p = self._ckpt_path(deck_idx, set_idx)
        if p.exists():
            try:
                d = json.loads(p.read_text("utf-8"))
                return _SetCheckpoint.from_dict(d)
            except Exception as e:
                log.warning("Failed to read checkpoint %s, starting fresh: %s", p, e)
        return _SetCheckpoint(deck_idx=deck_idx, set_idx=set_idx, target=self.cfg.target, variant=self.cfg.variant)

    def _save_ckpt(self, ckpt: _SetCheckpoint) -> None:
        p = self._ckpt_path(ckpt.deck_idx, ckpt.set_idx)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ckpt.to_dict(), ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, p)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _evenly_sample(items: list, k: int) -> list:
    """Return up to k items evenly spaced across the input list."""
    if len(items) <= k:
        return list(items)
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def _coerce_pair(src) -> tuple[str, str]:
    """Original prompts may be either [pos, neg] or a single string."""
    if isinstance(src, list) and len(src) >= 2:
        return str(src[0] or ""), str(src[1] or "")
    if isinstance(src, str):
        return src, ""
    if isinstance(src, dict):
        # Allow re-running on an SDXL-shaped source.
        pos = src.get("positive") or ", ".join(src.get("positive_tags", []) or [])
        neg = src.get("negative") or ", ".join(src.get("negative_tags", []) or [])
        return str(pos or ""), str(neg or "")
    return "", ""


def _name_match(query: str, *candidates: str | None) -> bool:
    q = query.strip().lower()
    for c in candidates:
        if c and c.strip().lower() == q:
            return True
    # fallback: substring match (helps with "Photojournalism" vs full description)
    for c in candidates:
        if c and q in c.strip().lower():
            return True
    return False


def _as_str_list(v: Any) -> list[str]:
    """Coerce model output into a list[str], dropping empties."""
    if v is None:
        return []
    if isinstance(v, str):
        # Tolerate the model returning a comma-separated string instead of a list.
        return [s.strip() for s in v.split(",") if s.strip()]
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _coerce_sdxl_entry(out: dict) -> dict:
    """Normalize a raw SDXL LLM response into the canonical entry shape."""
    pos = _as_str_list(out.get("positive_tags"))
    neg = _as_str_list(out.get("negative_tags"))
    raw_weights = out.get("weights") or {}
    weights: dict[str, float] = {}
    if isinstance(raw_weights, dict):
        for tag, w in raw_weights.items():
            try:
                weights[str(tag)] = float(w)
            except (TypeError, ValueError):
                continue
    raw_breaks = out.get("breaks") or []
    breaks: list[int] = []
    if isinstance(raw_breaks, list):
        for b in raw_breaks:
            try:
                breaks.append(int(b))
            except (TypeError, ValueError):
                continue
        breaks = sorted({b for b in breaks if 0 < b < len(pos)})
    return {
        "decision": str(out.get("decision", "") or ""),
        "shot_type": str(out.get("shot_type", "") or ""),
        "positive_tags": pos,
        "negative_tags": neg,
        "weights": weights,
        "breaks": breaks,
    }
