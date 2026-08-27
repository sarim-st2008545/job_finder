"""Generic RSS source.

Plug ANY RSS/Atom job feed into `feeds:` in settings.yaml. We use feedparser
which handles the parsing quirks across providers.
"""

from __future__ import annotations

from datetime import datetime
from time import mktime
from typing import Iterable

from ..logging_setup import get_logger
from . import register
from .base import JobSource, RawJob


logger = get_logger(__name__)


@register("rss")
class RSSSource(JobSource):
    name = "rss"

    def __init__(self, feeds: list[str] | None = None, **_) -> None:
        self.feeds = feeds or []

    def fetch(self, limit: int = 50) -> Iterable[RawJob]:
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser not installed; rss source disabled")
            return []

        results: list[RawJob] = []
        for url in self.feeds:
            if not url:
                continue
            try:
                parsed = feedparser.parse(url)
            except Exception as e:
                logger.warning("RSS fetch failed for %s: %s", url, e)
                continue
            for entry in parsed.entries:
                title = entry.get("title", "Unknown")
                link = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                company = _company_from_title(title)
                date_posted = None
                if getattr(entry, "published_parsed", None):
                    date_posted = datetime.fromtimestamp(
                        mktime(entry.published_parsed)
                    )
                results.append(
                    RawJob(
                        title=title,
                        company=company or parsed.feed.get("title", "Unknown"),
                        url=link,
                        source=self.name,
                        jd_text=summary,
                        date_posted=date_posted,
                        extra={"feed": url},
                    )
                )
                if len(results) >= limit:
                    logger.info("RSS: hit limit %d", limit)
                    return results
        logger.info("RSS: fetched %d jobs across %d feeds", len(results), len(self.feeds))
        return results


def _company_from_title(title: str) -> str | None:
    """Many job feeds format titles as 'Role at Company'."""
    for sep in [" at ", " @ ", " - ", " | "]:
        if sep in title:
            return title.split(sep, 1)[1].strip()
    return None
