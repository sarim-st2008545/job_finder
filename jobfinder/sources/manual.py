"""Manual source: feed a single URL or raw JD text into the pipeline.

Backbone for when you find a job by hand on LinkedIn/Glassdoor and want the
rest of the system to take over (match -> draft -> brief).
"""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse

from ..config import get_settings
from ..logging_setup import get_logger
from ..utils import http_client
from . import register
from .base import JobSource, RawJob


logger = get_logger(__name__)


@register("manual")
class ManualSource(JobSource):
    name = "manual"

    def __init__(
        self,
        url: str | None = None,
        jd_text: str | None = None,
        title: str = "Manually added job",
        company: str = "Unknown",
        **_,
    ) -> None:
        self.url = url
        self.jd_text = jd_text
        self.title = title
        self.company = company

    def fetch(self, limit: int = 50) -> Iterable[RawJob]:
        text = self.jd_text or ""
        html: str | None = None
        if self.url and not text:
            ua = get_settings().user_agent
            try:
                with http_client(user_agent=ua) as client:
                    resp = client.get(self.url)
                    resp.raise_for_status()
                    html = resp.text
                    text = _extract_main(html)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", self.url, e)

        host = urlparse(self.url).netloc if self.url else ""
        return [
            RawJob(
                title=self.title,
                company=self.company,
                url=self.url or f"manual://{self.title}",
                source=self.name,
                jd_text=text,
                raw_html=html,
                extra={"host": host},
            )
        ]


def _extract_main(html: str) -> str:
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, favor_recall=True)
        if text:
            return text
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "lxml").get_text("\n", strip=True)
    except Exception:
        return ""
