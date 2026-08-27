"""SQLite layer.

Intentionally written against stdlib `sqlite3` to keep the prototype's surface
area small. Schema is created on first use.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import get_settings
from .models import Application, Company, Contact, Job


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    url           TEXT NOT NULL,
    source        TEXT NOT NULL,
    raw_path      TEXT,
    jd_text       TEXT,
    location      TEXT,
    date_posted   TEXT,
    date_seen     TEXT NOT NULL,
    match_score   REAL,
    status        TEXT NOT NULL DEFAULT 'new',
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source  ON jobs(source);

CREATE TABLE IF NOT EXISTS companies (
    slug          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    domain        TEXT,
    brief_path    TEXT,
    vector_id     TEXT,
    last_scraped  TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    job_id          TEXT NOT NULL,
    profile_variant TEXT NOT NULL,
    resume_path     TEXT NOT NULL,
    cover_path      TEXT NOT NULL,
    match_path      TEXT NOT NULL,
    applied_date    TEXT,
    status          TEXT NOT NULL DEFAULT 'drafted',
    reviewer        TEXT,
    notes           TEXT,
    PRIMARY KEY (job_id, profile_variant),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS contacts (
    company_slug    TEXT NOT NULL,
    name            TEXT NOT NULL,
    title           TEXT,
    source_url      TEXT,
    email_candidate TEXT,
    confidence      REAL DEFAULT 0,
    PRIMARY KEY (company_slug, name)
);

CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    agent       TEXT NOT NULL,
    event       TEXT NOT NULL,
    payload     TEXT
);
"""


_local = threading.local()


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    Path(settings.paths.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.paths.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ---------- jobs ----------


def upsert_job(job: Job) -> None:
    with connection() as c:
        c.execute(
            """
            INSERT INTO jobs (id, title, company, url, source, raw_path, jd_text,
                              location, date_posted, date_seen, match_score, status, notes)
            VALUES (:id, :title, :company, :url, :source, :raw_path, :jd_text,
                    :location, :date_posted, :date_seen, :match_score, :status, :notes)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                company=excluded.company,
                url=excluded.url,
                source=excluded.source,
                raw_path=COALESCE(excluded.raw_path, jobs.raw_path),
                jd_text=COALESCE(excluded.jd_text, jobs.jd_text),
                location=COALESCE(excluded.location, jobs.location),
                date_posted=COALESCE(excluded.date_posted, jobs.date_posted),
                match_score=COALESCE(excluded.match_score, jobs.match_score),
                status=CASE
                  WHEN jobs.status IN ('scored', 'review_required', 'drafted', 'applied', 'rejected', 'skipped', 'archived')
                    THEN jobs.status
                  ELSE excluded.status
                END,
                notes=COALESCE(excluded.notes, jobs.notes)
            """,
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "url": job.url,
                "source": job.source,
                "raw_path": job.raw_path,
                "jd_text": job.jd_text,
                "location": job.location,
                "date_posted": _iso(job.date_posted),
                "date_seen": _iso(job.date_seen) or datetime.utcnow().isoformat(),
                "match_score": job.match_score,
                "status": job.status,
                "notes": job.notes,
            },
        )


def get_job(job_id: str) -> Job | None:
    with connection() as c:
        row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return _row_to_job(row)


def list_jobs(
    status: str | None = None,
    limit: int = 100,
    order_by: str = "date_seen DESC",
) -> list[Job]:
    q = "SELECT * FROM jobs"
    params: tuple[Any, ...] = ()
    if status:
        q += " WHERE status = ?"
        params = (status,)
    # order_by is a literal from our own code; safe.
    q += f" ORDER BY {order_by} LIMIT ?"
    params = params + (limit,)
    with connection() as c:
        rows = c.execute(q, params).fetchall()
        return [_row_to_job(r) for r in rows]


def jobs_for_report(limit: int = 500) -> list[Job]:
    """Jobs ordered for human review: scored first (best match first), then unscored."""
    with connection() as c:
        rows = c.execute(
            """
            SELECT * FROM jobs
            ORDER BY (match_score IS NULL) ASC, match_score DESC, date_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_job(r) for r in rows]


def set_job_status(job_id: str, status: str, match_score: float | None = None) -> None:
    with connection() as c:
        if match_score is not None:
            c.execute(
                "UPDATE jobs SET status = ?, match_score = ? WHERE id = ?",
                (status, match_score, job_id),
            )
        else:
            c.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        url=row["url"],
        source=row["source"],
        raw_path=row["raw_path"],
        jd_text=row["jd_text"],
        location=row["location"],
        date_posted=_parse_dt(row["date_posted"]),
        date_seen=_parse_dt(row["date_seen"]) or datetime.utcnow(),
        match_score=row["match_score"],
        status=row["status"],
        notes=row["notes"],
    )


# ---------- companies ----------


def upsert_company(company: Company) -> None:
    with connection() as c:
        c.execute(
            """
            INSERT INTO companies (slug, name, domain, brief_path, vector_id, last_scraped)
            VALUES (:slug, :name, :domain, :brief_path, :vector_id, :last_scraped)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name,
                domain=COALESCE(excluded.domain, companies.domain),
                brief_path=COALESCE(excluded.brief_path, companies.brief_path),
                vector_id=COALESCE(excluded.vector_id, companies.vector_id),
                last_scraped=COALESCE(excluded.last_scraped, companies.last_scraped)
            """,
            {
                "slug": company.slug,
                "name": company.name,
                "domain": company.domain,
                "brief_path": company.brief_path,
                "vector_id": company.vector_id,
                "last_scraped": _iso(company.last_scraped),
            },
        )


def get_company(slug: str) -> Company | None:
    with connection() as c:
        row = c.execute("SELECT * FROM companies WHERE slug = ?", (slug,)).fetchone()
        if not row:
            return None
        return Company(
            slug=row["slug"],
            name=row["name"],
            domain=row["domain"],
            brief_path=row["brief_path"],
            vector_id=row["vector_id"],
            last_scraped=_parse_dt(row["last_scraped"]),
        )


def list_companies(limit: int = 500) -> list[Company]:
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM companies ORDER BY name COLLATE NOCASE LIMIT ?",
            (limit,),
        ).fetchall()
        out: list[Company] = []
        for row in rows:
            out.append(
                Company(
                    slug=row["slug"],
                    name=row["name"],
                    domain=row["domain"],
                    brief_path=row["brief_path"],
                    vector_id=row["vector_id"],
                    last_scraped=_parse_dt(row["last_scraped"]),
                )
            )
        return out


# ---------- applications ----------


def upsert_application(app: Application) -> None:
    with connection() as c:
        c.execute(
            """
            INSERT INTO applications (job_id, profile_variant, resume_path, cover_path,
                                      match_path, applied_date, status, reviewer, notes)
            VALUES (:job_id, :profile_variant, :resume_path, :cover_path, :match_path,
                    :applied_date, :status, :reviewer, :notes)
            ON CONFLICT(job_id, profile_variant) DO UPDATE SET
                resume_path=excluded.resume_path,
                cover_path=excluded.cover_path,
                match_path=excluded.match_path,
                applied_date=COALESCE(excluded.applied_date, applications.applied_date),
                status=excluded.status,
                reviewer=COALESCE(excluded.reviewer, applications.reviewer),
                notes=COALESCE(excluded.notes, applications.notes)
            """,
            {
                "job_id": app.job_id,
                "profile_variant": app.profile_variant,
                "resume_path": app.resume_path,
                "cover_path": app.cover_path,
                "match_path": app.match_path,
                "applied_date": _iso(app.applied_date),
                "status": app.status,
                "reviewer": app.reviewer,
                "notes": app.notes,
            },
        )


# ---------- contacts ----------


def upsert_contact(contact: Contact) -> None:
    with connection() as c:
        c.execute(
            """
            INSERT INTO contacts (company_slug, name, title, source_url, email_candidate, confidence)
            VALUES (:company_slug, :name, :title, :source_url, :email_candidate, :confidence)
            ON CONFLICT(company_slug, name) DO UPDATE SET
                title=COALESCE(excluded.title, contacts.title),
                source_url=COALESCE(excluded.source_url, contacts.source_url),
                email_candidate=COALESCE(excluded.email_candidate, contacts.email_candidate),
                confidence=excluded.confidence
            """,
            contact.model_dump(),
        )


# ---------- audit log ----------


def log_event(agent: str, event: str, payload: dict[str, Any] | None = None) -> None:
    with connection() as c:
        c.execute(
            "INSERT INTO run_log (ts, agent, event, payload) VALUES (?, ?, ?, ?)",
            (
                datetime.utcnow().isoformat(),
                agent,
                event,
                json.dumps(payload or {}, default=str),
            ),
        )


def recent_events(limit: int = 50) -> list[dict[str, Any]]:
    with connection() as c:
        rows = c.execute(
            "SELECT ts, agent, event, payload FROM run_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            payload: Any = r["payload"]
            try:
                payload = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                pass
            out.append(
                {"ts": r["ts"], "agent": r["agent"], "event": r["event"], "payload": payload}
            )
        return out


def counts_by_status() -> dict[str, int]:
    with connection() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}
