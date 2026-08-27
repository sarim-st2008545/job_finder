"""Pluggable job-source registry."""

from __future__ import annotations

from typing import Callable

from .base import JobSource, RawJob

_REGISTRY: dict[str, Callable[..., JobSource]] = {}


def register(name: str):
    def deco(cls):
        _REGISTRY[name] = cls
        return cls

    return deco


def build_source(name: str, **opts) -> JobSource | None:
    factory = _REGISTRY.get(name)
    if not factory:
        return None
    return factory(**opts)


# Import side-effect: registers built-in sources
from . import remoteok  # noqa: F401
from . import rss  # noqa: F401
from . import manual  # noqa: F401
from . import linkedin_playwright  # noqa: F401

__all__ = ["JobSource", "RawJob", "register", "build_source"]
