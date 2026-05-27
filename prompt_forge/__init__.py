"""prompt_forge: convert conceptual JSON prompt decks into production-ready
[positive, negative] pairs using a local LLM (Ollama or LM Studio).
"""
# Define ``__version__`` BEFORE the submodule imports so children that read it
# at import time (e.g. ``llm_client`` building its User-Agent) see the real
# value rather than the defensive fallback.
__version__ = "0.4.0"

from .llm_client import (
    LLMClient,
    LLMConfig,
    LLMError,
    LMStudioClient,
    OllamaClient,
    make_client,
)

# Backwards-compatible aliases.
OllamaConfig = LLMConfig
OllamaError = LLMError

from .pipeline import Pipeline, PipelineConfig, RunSelection
from .templates import FLUX_BANK, SDXL_BANK, TemplateBank, Target, select_templates
from .ui_server import main as ui_main, serve as ui_serve
from .validator import (
    ValidationResult,
    estimate_clip_tokens,
    render_sdxl_negative,
    render_sdxl_positive,
    validate_pair,
    validate_sdxl_pair,
)

__all__ = [
    "LLMClient",
    "LLMConfig",
    "LLMError",
    "LMStudioClient",
    "OllamaClient",
    "OllamaConfig",
    "OllamaError",
    "make_client",
    "Pipeline",
    "PipelineConfig",
    "RunSelection",
    "Target",
    "TemplateBank",
    "FLUX_BANK",
    "SDXL_BANK",
    "select_templates",
    "validate_pair",
    "validate_sdxl_pair",
    "render_sdxl_positive",
    "render_sdxl_negative",
    "estimate_clip_tokens",
    "ValidationResult",
    "ui_main",
    "ui_serve",
]

# __version__ is defined at the top of this module.
