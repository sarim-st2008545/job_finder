"""RemoteOK source. Uses their public JSON endpoint (no auth, free)."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..config import get_settings
from ..logging_setup import get_logger
from ..utils import http_client
from . import register
from .base import JobSource, RawJob


logger = get_logger(__name__)


@register("remoteok")
class RemoteOKSource(JobSource):
    name = "remoteok"
    ENDPOINT = "https://remoteok.com/api"

    def __init__(self, tags: list[str] | None = None, **_) -> None:
        self.tags = [t.lower() for t in (tags or [])]

    def fetch(self, limit: int = 50) -> Iterable[RawJob]:
        ua = get_settings().user_agent
        with http_client(user_agent=ua) as client:
            try:
                resp = client.get(self.ENDPOINT)
                resp.raise_for_status()
                items = resp.json()
            except Exception as e:
                logger.warning("RemoteOK fetch failed: %s", e)
                return []

        # First item is a metadata blob, skip it.
        items = [i for i in items if isinstance(i, dict) and i.get("id")]
        results: list[RawJob] = []
        for item in items:
            tags = [t.lower() for t in item.get("tags", []) if isinstance(t, str)]
            if self.tags and not any(t in tags for t in self.tags):
                continue
            results.append(
                RawJob(
                    title=item.get("position") or item.get("title") or "Unknown",
                    company=item.get("company") or "Unknown",
                    url=item.get("url")
                    or f"https://remoteok.com/remote-jobs/{item['id']}",
                    source=self.name,
                    location=item.get("location") or "Remote",
                    jd_text=item.get("description") or "",
                    date_posted=_parse_dt(item.get("date")),
                    extra={"tags": tags, "id": str(item.get("id"))},
                )
            )
            if len(results) >= limit:
                break
        logger.info("RemoteOK: fetched %d jobs (limit=%d)", len(results), limit)
        return results


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
