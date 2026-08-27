"""Structured logging with both console (Rich) and JSON-lines file sinks."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

from .config import get_settings


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k.startswith("ctx_"):
                payload[k[4:]] = v
        return json.dumps(payload, default=str)


_configured = False


def setup_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    log_level = (level or settings.env.get("LOG_LEVEL", "INFO")).upper()

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    console = RichHandler(rich_tracebacks=True, show_time=True, show_path=False)
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    Path(settings.paths.logs_dir).mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        settings.paths.logs_dir / "jobfinder.log.jsonl",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(JsonLinesFormatter())
    root.addHandler(fh)

    # quiet down some noisy libs
    for noisy in ("httpx", "httpcore", "urllib3", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
