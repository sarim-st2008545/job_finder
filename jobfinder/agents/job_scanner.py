"""Job-Scanner Agent.

Walks all enabled sources, applies user filters, writes raw payloads to disk,
and upserts new postings into SQLite. Idempotent and dedupes via stable IDs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import upsert_job
from ..models import Job
from ..sources import RawJob, build_source
from ..utils import stable_id, write_text
from .base import BaseAgent


class JobScannerAgent(BaseAgent):
    name = "job_scanner"

    def run(self, source_overrides: list[dict[str, Any]] | None = None) -> list[Job]:
        cfg = dict(self.settings.scanner)
        max_per_run = int(cfg.get("max_jobs_per_run", 50))
        sources_cfg = source_overrides or cfg.get("sources", [])

        filters = self.settings.filters or {}

        ingested: list[Job] = []
        for sconf in sources_cfg:
            if not sconf.get("enabled", True if source_overrides else False):
                continue
            sname = sconf["name"]
            opts = {k: v for k, v in sconf.items() if k not in ("name", "enabled")}
            source = build_source(sname, **opts)
            if source is None:
                self.log.warning("Unknown source '%s' — skipping", sname)
                continue
            self.emit("source.start", {"source": sname, "opts": _safe(opts)})
            try:
                raw_jobs = list(source.fetch(limit=max_per_run))
            except Exception as e:
                self.log.exception("Source '%s' crashed: %s", sname, e)
                self.emit("source.error", {"source": sname, "error": str(e)})
                continue

            for raw in raw_jobs:
                if not _passes_filters(raw, filters):
                    continue
                job = self._persist(raw)
                ingested.append(job)
                if len(ingested) >= max_per_run:
                    break
            self.emit("source.end", {"source": sname, "kept": len(ingested)})
            if len(ingested) >= max_per_run:
                break

        self.emit("run.end", {"total_ingested": len(ingested)})
        return ingested

    def _persist(self, raw: RawJob) -> Job:
        job_id = stable_id(raw.source, raw.company, raw.title, raw.url)
        raw_path = None
        if raw.raw_html:
            raw_path = str(self.settings.paths.raw_jobs_dir / f"{job_id}.html")
            write_text(self.settings.paths.raw_jobs_dir / f"{job_id}.html", raw.raw_html)
        elif raw.jd_text:
            raw_path = str(self.settings.paths.raw_jobs_dir / f"{job_id}.txt")
            write_text(self.settings.paths.raw_jobs_dir / f"{job_id}.txt", raw.jd_text)

        job = Job(
            id=job_id,
            title=raw.title.strip(),
            company=raw.company.strip(),
            url=raw.url,
            source=raw.source,
            location=raw.location,
            jd_text=raw.jd_text,
            raw_path=raw_path,
            date_posted=raw.date_posted,
            date_seen=datetime.utcnow(),
            status="new",
        )
        upsert_job(job)
        self.emit(
            "job.ingested",
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "source": job.source,
            },
        )
        return job


def _passes_filters(raw: RawJob, filters: dict[str, Any]) -> bool:
    text = " ".join(
        filter(None, [raw.title, raw.company, raw.location or "", raw.jd_text or ""])
    ).lower()

    must_inc = [t.lower() for t in filters.get("must_include_any") or []]
    must_exc = [t.lower() for t in filters.get("must_exclude_any") or []]
    if must_inc and not any(t in text for t in must_inc):
        return False
    if must_exc and any(t in text for t in must_exc):
        return False

    if filters.get("remote_only") and "remote" not in (raw.location or "").lower():
        return False

    locs = [l.lower() for l in filters.get("locations_allow") or []]
    if locs:
        loc = (raw.location or "").lower()
        if loc and not any(l in loc for l in locs):
            return False

    return True


def _safe(opts: dict[str, Any]) -> dict[str, Any]:
    """Strip noisy/long values from log payloads."""
    out = {}
    for k, v in opts.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        else:
            out[k] = v
    return out
