"""Structural validation for rewritten prompt pairs.

These checks correspond to spec section 5 ("How to Validate Your Output").
A failure produces a list of human-readable issues; the pipeline can use that
to ask the LLM for a single repair pass before accepting a result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Vocabularies kept module-level so we can reuse them in unit tests.

SHOT_TYPES = (
    "close-up",
    "extreme close-up",
    "medium shot",
    "medium-long shot",
    "wide shot",
    "establishing shot",
    "overhead shot",
    "high-angle shot",
    "low-angle shot",
    "three-quarter portrait",
    "full-body shot",
    "macro shot",
    "portrait",  # softer fallback; prefer explicit shot types
)

REQUIRED_NEGATIVE_THEMES = (
    # at least one phrase from each tuple must appear
    ("noise", "film grain", "analog noise", "grit", "dust", "scratches"),
    ("low quality", "low resolution", "jpeg"),
    ("watercolor", "oil painting", "illustration", "anime", "cartoon", "comic", "vector art"),
    ("3d render", "octane render", "cg", "cgsociety"),
    ("beauty filter", "plastic skin", "waxy skin", "airbrushed", "doll-like"),
    ("gaussian blur",),
    ("text", "logo", "watermark"),
)

MONOCHROME_LEAK = re.compile(
    r"\b(monochrome|black[\s-]and[\s-]white|grayscale|greyscale|sepia|silver gelatin)\b",
    re.IGNORECASE,
)

OPENING_RE = re.compile(
    r"^\s*realistic\s+photographic\s+([a-zA-Z\-]+(?:\s+[a-zA-Z\-]+){0,3})\s+of\b",
    re.IGNORECASE,
)


@dataclass
class ValidationResult:
    ok: bool
    issues: list[str]


def validate_pair(positive: str, negative: str, *, allow_mono_in_neg: bool = True) -> ValidationResult:
    issues: list[str] = []

    # ---- positive ---------------------------------------------------------
    if not positive or not positive.strip():
        issues.append("positive: empty")
    else:
        m = OPENING_RE.match(positive)
        if not m:
            issues.append(
                'positive: must open with "realistic photographic <shot type> of ..."'
            )
        else:
            shot = m.group(1).lower()
            if not any(s in shot or shot in s for s in SHOT_TYPES):
                issues.append(f"positive: opening shot type '{shot}' is not a recognized cinematographic term")

        # Monochrome leak check (we want full-color images).
        if MONOCHROME_LEAK.search(positive):
            issues.append("positive: contains monochrome/B&W language; output must be full-color")

        # Heuristic content checks.
        if "\n" in positive:
            issues.append("positive: contains line breaks; must be a single paragraph")
        if len(positive.split()) < 35:
            issues.append("positive: too short to satisfy the detail requirements")
        if not _mentions_lighting(positive):
            issues.append("positive: missing lighting direction/quality cues")
        if not _mentions_texture(positive):
            issues.append("positive: missing texture cues (skin/hair/fabric/surface)")

    # ---- negative ---------------------------------------------------------
    if not negative or not negative.strip():
        issues.append("negative: empty")
    else:
        if "." in negative and not re.search(r"\b(\d\.\d|f/?\d|\.\s*$)", negative):
            # Heuristic: real sentences usually end with ". " mid-string.
            if re.search(r"[a-z]\.\s+[A-Z]", negative):
                issues.append("negative: appears to contain sentences; must be comma-separated phrases")

        lower_neg = negative.lower()
        for theme in REQUIRED_NEGATIVE_THEMES:
            if not any(term in lower_neg for term in theme):
                issues.append(f"negative: missing baseline term from {theme!r}")

    return ValidationResult(ok=not issues, issues=issues)


# ---------------------------------------------------------------------------

_LIGHTING_WORDS = (
    "light", "lit", "lighting", "backlight", "rim light", "fill", "key light",
    "bloom", "halation", "highlight", "shadow", "silhouette", "glow", "sun",
    "lamp", "fresnel", "softbox", "window light", "match", "beam",
)
_TEXTURE_WORDS = (
    "pore", "wrinkle", "freckle", "strand", "lash", "brow",
    "weave", "fold", "crease", "fabric", "silk", "velvet", "lace",
    "wood grain", "plaster", "concrete", "tile", "sand", "fog", "water",
    "metal", "chrome", "scuff", "stitch", "crack", "rust",
)


def _mentions_lighting(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in _LIGHTING_WORDS)


def _mentions_texture(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in _TEXTURE_WORDS)


# ===========================================================================
# SDXL validation
# ===========================================================================

# Coarse CLIP-token estimator. Real CLIP BPE merges punctuation into tokens,
# but for budget enforcement we just need a stable lower-bound estimate that
# tracks tag count + average word count well. Per CLIP empirics, a typical
# short tag phrase is ~2-4 tokens. We approximate: 1 token per word + 1 per
# tag (for the trailing comma/separator). This slightly over-estimates short
# tags and slightly under-estimates very long ones, which is the right bias
# for staying under the 75-per-chunk hard limit.

SDXL_MAX_TOTAL_TOKENS = 225  # 3 chunks of 75
SDXL_MAX_CHUNK_TOKENS = 75

# Required negative themes for SDXL. Mostly the same vocab as FLUX, restated
# in CLIP-tag style.
SDXL_REQUIRED_NEGATIVE_THEMES = (
    ("3d render", "octane render", "cgi", "cgsociety"),
    ("illustration", "painting", "drawing", "anime", "cartoon", "comic", "vector art", "concept art"),
    ("blurry", "out of focus", "motion blur", "gaussian blur"),
    ("low quality", "lowres", "worst quality", "jpeg"),
    ("deformed", "mutated", "bad anatomy", "bad hands", "extra fingers", "extra limbs"),
    ("watermark", "signature", "text", "logo"),
    ("plastic skin", "waxy skin", "airbrushed", "smooth skin", "doll-like", "beauty filter"),
)


def estimate_clip_tokens(tag: str) -> int:
    """Rough CLIP-token count for one tag string."""
    if not tag:
        return 0
    # word count + 1 separator token; minimum 2 (most tags are >=1 word + comma)
    words = max(1, len(tag.split()))
    return words + 1


def render_sdxl_positive(
    positive_tags: list[str],
    weights: dict[str, float] | None = None,
    breaks: list[int] | None = None,
) -> str:
    """Render an SDXL positive tag list to the final prompt string.

    Inserts ``BREAK`` at each `breaks` index, wraps weighted tags in
    ``(tag:1.2)`` format, and joins with ", ". This is the canonical
    rendering used both for downstream consumers and for token-budget
    validation here.
    """
    weights = weights or {}
    breaks = breaks or []
    break_set = {int(i) for i in breaks if isinstance(i, (int, float))}
    parts: list[str] = []
    for idx, tag in enumerate(positive_tags):
        if idx in break_set:
            parts.append("BREAK")
        w = weights.get(tag)
        if w is not None and abs(float(w) - 1.0) > 1e-6:
            parts.append(f"({tag}:{float(w):.2f})")
        else:
            parts.append(tag)
    return ", ".join(parts)


def render_sdxl_negative(
    negative_tags: list[str],
    weights: dict[str, float] | None = None,
) -> str:
    """Render an SDXL negative tag list to the final prompt string."""
    weights = weights or {}
    parts: list[str] = []
    for tag in negative_tags:
        w = weights.get(tag)
        if w is not None and abs(float(w) - 1.0) > 1e-6:
            parts.append(f"({tag}:{float(w):.2f})")
        else:
            parts.append(tag)
    return ", ".join(parts)


def _chunk_tokens(positive_tags: list[str], breaks: list[int] | None) -> list[int]:
    """Return the token count of each CLIP chunk (split at BREAK boundaries)."""
    breaks = sorted({int(i) for i in (breaks or []) if isinstance(i, (int, float))})
    boundaries = [0, *breaks, len(positive_tags)]
    chunks: list[int] = []
    for a, b in zip(boundaries, boundaries[1:]):
        if a == b:
            continue
        chunks.append(sum(estimate_clip_tokens(t) for t in positive_tags[a:b]))
    return chunks


def validate_sdxl_pair(pair: dict) -> ValidationResult:
    """Validate an SDXL prompt object.

    Expected keys: positive_tags (list[str]), negative_tags (list[str]),
    optional weights (dict[str,float]) and breaks (list[int]).
    """
    issues: list[str] = []

    pos = pair.get("positive_tags") or []
    neg = pair.get("negative_tags") or []
    weights = pair.get("weights") or {}
    breaks = pair.get("breaks") or []

    # ---- positive --------------------------------------------------------
    if not isinstance(pos, list) or not pos:
        issues.append("positive_tags: empty or not a list")
    else:
        # First few tags must mention a concrete shot type.
        head = " ".join(str(t).lower() for t in pos[:6])
        if not any(s in head for s in SHOT_TYPES):
            issues.append(
                "positive_tags: a concrete cinematographic shot type must "
                "appear in the first 6 tags (e.g. 'medium shot', 'close-up')"
            )
        # Monochrome leak check (positive must stay full-color).
        joined_pos = " , ".join(str(t) for t in pos)
        if MONOCHROME_LEAK.search(joined_pos):
            issues.append("positive_tags: contains monochrome/B&W tags; output must be full-color")
        # Lighting and texture cues somewhere.
        if not _mentions_lighting(joined_pos):
            issues.append("positive_tags: missing lighting cues (e.g. 'rim light', 'soft window light')")
        if not _mentions_texture(joined_pos):
            issues.append("positive_tags: missing texture cues (e.g. 'visible skin pores', 'fabric weave')")
        # Banned prose joiners.
        for banned in (" and ", " while ", " with ", " of the "):
            if any(banned in f" {str(t).lower()} " for t in pos):
                issues.append(f"positive_tags: tags contain prose joiner '{banned.strip()}' - use atomic tag phrases")
                break

    # ---- breaks ----------------------------------------------------------
    if breaks:
        prev = -1
        for b in breaks:
            if not isinstance(b, (int, float)) or int(b) <= 0 or int(b) >= len(pos):
                issues.append(f"breaks: index {b!r} is out of range (1..{len(pos) - 1})")
                break
            if int(b) <= prev:
                issues.append("breaks: indexes must be strictly increasing")
                break
            prev = int(b)

    # ---- token budget ----------------------------------------------------
    if isinstance(pos, list) and pos:
        chunks = _chunk_tokens(pos, breaks)
        total = sum(chunks)
        if total > SDXL_MAX_TOTAL_TOKENS:
            issues.append(
                f"positive_tags: estimated {total} CLIP tokens exceeds budget "
                f"of {SDXL_MAX_TOTAL_TOKENS} (3 chunks of {SDXL_MAX_CHUNK_TOKENS}); trim or compress tags"
            )
        for i, c in enumerate(chunks):
            if c > SDXL_MAX_CHUNK_TOKENS:
                issues.append(
                    f"positive_tags: chunk {i + 1} estimated at {c} tokens exceeds {SDXL_MAX_CHUNK_TOKENS}; "
                    "insert an additional BREAK"
                )

    # ---- weights ---------------------------------------------------------
    if weights:
        if not isinstance(weights, dict):
            issues.append("weights: must be an object mapping tag -> float")
        else:
            known = set(pos) | set(neg)
            for tag, w in weights.items():
                try:
                    wf = float(w)
                except (TypeError, ValueError):
                    issues.append(f"weights: '{tag}' has non-numeric weight {w!r}")
                    continue
                if wf < 0.5 or wf > 1.4:
                    issues.append(f"weights: '{tag}' weight {wf} outside allowed range 0.5-1.4")
                if tag not in known:
                    issues.append(f"weights: '{tag}' references a tag not present in positive_tags or negative_tags")

    # ---- negative --------------------------------------------------------
    if not isinstance(neg, list) or not neg:
        issues.append("negative_tags: empty or not a list")
    else:
        lower_neg = " , ".join(str(t).lower() for t in neg)
        for theme in SDXL_REQUIRED_NEGATIVE_THEMES:
            if not any(term in lower_neg for term in theme):
                issues.append(f"negative_tags: missing baseline term from {theme!r}")

    return ValidationResult(ok=not issues, issues=issues)
