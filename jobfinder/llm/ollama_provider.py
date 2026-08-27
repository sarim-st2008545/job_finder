"""Ollama local provider (free, runs on your machine)."""

from __future__ import annotations

import os

from .base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str) -> None:
        super().__init__(model)
        try:
            import ollama
        except ImportError as e:
            raise RuntimeError(
                "ollama package is not installed. `pip install ollama`"
            ) from e
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self._client = ollama.Client(host=host)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        resp = self._client.chat(
            model=self.model,
            messages=(
                ([{"role": "system", "content": system}] if system else [])
                + [{"role": "user", "content": prompt}]
            ),
            options={"temperature": temperature, "num_predict": max_tokens},
        )
        text = (resp.get("message", {}) or {}).get("content", "").strip()
        return LLMResponse(text=text, provider=self.name, model=self.model, raw=resp)
