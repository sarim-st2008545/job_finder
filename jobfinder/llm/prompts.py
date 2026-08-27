"""Tiny Jinja-based prompt loader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from ..config import get_settings


@lru_cache(maxsize=1)
def _env() -> Environment:
    settings = get_settings()
    return Environment(
        loader=FileSystemLoader(str(settings.paths.prompts_dir)),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(template_name: str, **ctx) -> str:
    """Render a prompt template by filename (relative to prompts/)."""
    tpl = _env().get_template(template_name)
    return tpl.render(**ctx)


def write_template(name: str, content: str) -> Path:
    """Persist a template (used by `init` command)."""
    settings = get_settings()
    path = settings.paths.prompts_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
