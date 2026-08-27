"""LinkedIn jobs via Playwright.

IMPORTANT: LinkedIn's ToS forbids automated scraping of authenticated pages.
This source defaults to **public, unauthenticated** job search results and is
intended for personal, low-volume use. Use responsibly and consider relying on
LinkedIn job-alert emails forwarded to a folder you ingest instead.

Run once before first use:
    playwright install chromium
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import quote_plus

from ..logging_setup import get_logger
from . import register
from .base import JobSource, RawJob


logger = get_logger(__name__)


@register("linkedin_playwright")
class LinkedInPlaywrightSource(JobSource):
    name = "linkedin_playwright"
    BASE = "https://www.linkedin.com/jobs/search/?keywords={kw}&location={loc}&start={start}"

    def __init__(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        max_pages: int = 2,
        headless: bool = True,
        **_,
    ) -> None:
        self.keywords = keywords or ["software engineer"]
        self.locations = locations or ["Remote"]
        self.max_pages = max_pages
        self.headless = headless

    def fetch(self, limit: int = 50) -> Iterable[RawJob]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning(
                "playwright not installed; run `pip install playwright && playwright install chromium`"
            )
            return []

        results: list[RawJob] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            ctx = browser.new_context(user_agent=_UA)
            page = ctx.new_page()
            for kw in self.keywords:
                for loc in self.locations:
                    for page_idx in range(self.max_pages):
                        url = self.BASE.format(
                            kw=quote_plus(kw),
                            loc=quote_plus(loc),
                            start=page_idx * 25,
                        )
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=20000)
                            page.wait_for_timeout(1500)  # let JS settle
                        except Exception as e:
                            logger.warning("LinkedIn page nav failed: %s", e)
                            continue
                        cards = page.locator("ul.jobs-search__results-list > li")
                        n = min(cards.count(), 25)
                        for i in range(n):
                            card = cards.nth(i)
                            try:
                                title = card.locator(
                                    ".base-search-card__title"
                                ).inner_text(timeout=2000).strip()
                                company = card.locator(
                                    ".base-search-card__subtitle"
                                ).inner_text(timeout=2000).strip()
                                location = card.locator(
                                    ".job-search-card__location"
                                ).inner_text(timeout=2000).strip()
                                link = (
                                    card.locator("a.base-card__full-link").get_attribute(
                                        "href", timeout=2000
                                    )
                                    or ""
                                )
                                link = re.sub(r"\?.*$", "", link)
                            except Exception:
                                continue
                            results.append(
                                RawJob(
                                    title=title,
                                    company=company,
                                    url=link,
                                    source=self.name,
                                    location=location,
                                    jd_text="",  # detail page scrape skipped for now
                                    extra={"keyword": kw, "search_location": loc},
                                )
                            )
                            if len(results) >= limit:
                                browser.close()
                                return results
            browser.close()
        logger.info("LinkedIn(public): fetched %d jobs", len(results))
        return results


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
