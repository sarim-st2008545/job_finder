"""Base class for job sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable


@dataclass
class RawJob:
    title: str
    company: str
    url: str
    source: str
    location: str | None = None
    jd_text: str | None = None
    raw_html: str | None = None
    date_posted: datetime | None = None
    extra: dict = field(default_factory=dict)


class JobSource(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, limit: int = 50) -> Iterable[RawJob]:
        raise NotImplementedError
