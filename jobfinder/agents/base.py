"""Base class for all agents.

We keep it minimal: each agent owns a `run(...)` method, has access to settings
and a logger, and emits audit events to the DB so the run log is searchable.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings, get_settings
from ..db import log_event
from ..logging_setup import get_logger


class BaseAgent:
    name: str = "base"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.log = get_logger(f"agent.{self.name}")

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        self.log.info("%s: %s", event, payload or {})
        log_event(self.name, event, payload)
