"""Backwards-compatible re-exports.

The provider abstraction lives in :mod:`prompt_forge.llm_client`. This module
keeps the original symbol names alive so existing imports
(``from prompt_forge.ollama_client import OllamaClient``) continue to work.
"""
from .llm_client import (
    LLMConfig as OllamaConfig,
    LLMError as OllamaError,
    OllamaClient,
)

__all__ = ["OllamaClient", "OllamaConfig", "OllamaError"]
