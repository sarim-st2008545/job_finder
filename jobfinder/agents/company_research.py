"""Company-R&D Agent.

For a given company name (and optional domain), fetch a small set of public
sources, render a one-page brief via the LLM, index it in the vector store,
and update the `companies` table.

Sources currently used:
  - Company homepage and /about /careers (if discoverable)
  - DuckDuckGo HTML search for "<company> news"
  - Wikipedia (light)
  - Crunchbase (org page if found — light scrape)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import tldextract

from ..config import load_profile
from ..db import upsert_company
from ..llm import get_provider
from ..llm.prompts import render
from ..models import Company
from ..utils import http_client, slug, write_text
from ..vectorstore import get_store
from .base import BaseAgent


@dataclass
class Source:
    kind: str
    url: str
    text: str


@dataclass
class BriefResult:
    company: Company
    sources: list[Source] = field(default_factory=list)
    brief_path: Path | None = None


class CompanyResearchAgent(BaseAgent):
    name = "company_research"

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.profile = load_profile(self.settings)
        self.provider = get_provider()
        self.cfg = self.settings.company_research or {}

    # ---------- public ----------

    def run(self, company_name: str, domain: str | None = None) -> BriefResult:
        sl = slug(company_name)
        self.emit("brief.start", {"company": company_name, "slug": sl, "domain": domain})

        domain = domain or _guess_domain(company_name)
        sources = self._gather(company_name, domain)
        brief_md = self._compose(company_name, domain, sources)

        out_dir: Path = self.settings.paths.companies_dir / sl
        out_dir.mkdir(parents=True, exist_ok=True)
        brief_path = out_dir / "brief.md"
        write_text(brief_path, brief_md)

        # Drop raw sources next to the brief for auditability
        write_text(
            out_dir / "sources.md",
            "\n\n".join(f"## [{i+1}] {s.kind} — {s.url}\n\n{s.text}" for i, s in enumerate(sources)),
        )

        # Vector index
        store = get_store()
        store.add(
            collection="companies",
            ids=[sl],
            documents=[brief_md],
            metadatas=[{"company": company_name, "domain": domain or ""}],
        )

        company = Company(
            slug=sl,
            name=company_name,
            domain=domain,
            brief_path=str(brief_path),
            vector_id=sl,
            last_scraped=datetime.utcnow(),
        )
        upsert_company(company)
        self.emit("brief.end", {"slug": sl, "sources": len(sources)})
        return BriefResult(company=company, sources=sources, brief_path=brief_path)

    # ---------- internals ----------

    def _gather(self, name: str, domain: str | None) -> list[Source]:
        sources: list[Source] = []
        ua = self.settings.user_agent
        max_pages = int(self.cfg.get("max_pages_per_company", 8))

        with http_client(user_agent=ua) as client:
            for url in _candidate_urls(name, domain):
                if len(sources) >= max_pages:
                    break
                try:
                    r = client.get(url)
                    if r.status_code != 200 or not r.text:
                        continue
                    text = _extract_text(r.text)[:4000]
                    if not text:
                        continue
                    sources.append(Source(kind=_kind_for(url), url=url, text=text))
                except Exception as e:
                    self.log.debug("fetch %s failed: %s", url, e)

            # DuckDuckGo HTML search for news
            try:
                q = f"{name} news"
                r = client.get(
                    "https://duckduckgo.com/html/", params={"q": q}, timeout=15
                )
                if r.status_code == 200:
                    items = _parse_ddg(r.text, max_items=int(self.cfg.get("max_news_items", 5)))
                    for item in items:
                        if len(sources) >= max_pages:
                            break
                        sources.append(Source(kind="news", url=item["url"], text=item["snippet"]))
            except Exception as e:
                self.log.debug("ddg search failed: %s", e)

        return sources

    def _compose(self, name: str, domain: str | None, sources: list[Source]) -> str:
        prompt = render(
            "company_brief_prompt.tpl",
            company_name=name,
            domain=domain or "",
            profile_summary=_profile_summary(self.profile),
            sources=[{"kind": s.kind, "url": s.url, "text": s.text} for s in sources],
        )
        try:
            resp = self.provider.complete(prompt, temperature=0.2, max_tokens=1400)
            return resp.text or _fallback_brief(name, sources)
        except Exception as e:
            self.log.warning("Brief generation failed (%s); writing fallback", e)
            return _fallback_brief(name, sources)


# ---------- helpers ----------


def _profile_summary(profile: dict) -> str:
    basics = profile.get("basics", {}) or {}
    skills = profile.get("skills", {}) or {}
    return (
        f"{basics.get('headline', '')}. "
        f"Primary skills: {', '.join(skills.get('primary', []) or [])}."
    )


def _guess_domain(name: str) -> str | None:
    s = slug(name).replace("-", "")
    if not s:
        return None
    return f"{s}.com"


def _candidate_urls(name: str, domain: str | None) -> list[str]:
    urls: list[str] = []
    if domain:
        for path in ("", "/about", "/about-us", "/company", "/careers", "/jobs"):
            urls.append(f"https://{domain}{path}")
    s = slug(name)
    urls.append(f"https://en.wikipedia.org/wiki/{s.replace('-', '_').title()}")
    urls.append(f"https://www.crunchbase.com/organization/{s}")
    return urls


def _kind_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "wikipedia.org" in host:
        return "wikipedia"
    if "crunchbase.com" in host:
        return "crunchbase"
    if "linkedin.com" in host:
        return "linkedin"
    return "website"


def _extract_text(html: str) -> str:
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, favor_recall=False)
        if text:
            return text
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "lxml").get_text("\n", strip=True)
    except Exception:
        return ""


def _parse_ddg(html: str, max_items: int = 5) -> list[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for a in soup.select("a.result__a"):
        url = a.get("href")
        snippet = a.find_parent("div", class_="result")
        text = snippet.get_text(" ", strip=True) if snippet else (a.get_text(strip=True) or "")
        if url:
            out.append({"url": url, "snippet": text[:600]})
        if len(out) >= max_items:
            break
    return out


def _fallback_brief(name: str, sources: list[Source]) -> str:
    head = f"# {name} — Brief\n\n## TL;DR\nAutomatic gather only; LLM unavailable.\n\n"
    return head + "## Sources\n" + "\n".join(f"- [{s.kind}] {s.url}" for s in sources)
