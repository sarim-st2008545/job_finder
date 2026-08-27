"""Abstract base for LLM providers."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    raw: Any = None

    def parse_json(self, default: Any = None) -> Any:
        """Best-effort JSON extraction. Tolerates fenced code blocks."""
        text = self.text.strip()
        match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
        if not match:
            return default
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            try:
                # second-chance: trim trailing commas
                cleaned = re.sub(r",\s*([}\]])", r"\1", match.group(0))
                return json.loads(cleaned)
            except json.JSONDecodeError:
                return default


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Plain text completion."""
        raise NotImplementedError
