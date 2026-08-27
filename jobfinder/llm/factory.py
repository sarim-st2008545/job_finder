"""Selects an LLM provider based on settings/env. Always falls back to mock."""

from __future__ import annotations

import logging
from functools import lru_cache

from ..config import get_settings
from .base import LLMProvider
from .mock import MockProvider

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def get_provider(provider: str | None = None, model: str | None = None) -> LLMProvider:
    s = get_settings()
    name = (provider or s.llm_provider or "mock").lower()
    chosen_model = model or s.llm_model

    try:
        if name == "openai":
            from .openai_provider import OpenAIProvider

            return OpenAIProvider(chosen_model)
        if name == "anthropic":
            from .anthropic_provider import AnthropicProvider

            return AnthropicProvider(chosen_model)
        if name == "ollama":
            from .ollama_provider import OllamaProvider

            return OllamaProvider(chosen_model)
        if name == "mock":
            return MockProvider(chosen_model)
    except Exception as e:
        logger.warning(
            "LLM provider '%s' failed to initialize (%s). Falling back to mock.",
            name,
            e,
        )

    return MockProvider(chosen_model)
