"""Consolidated opportunities report (Markdown).

Produces one file you can open locally: ranked roles, company roll-up, and
suggested follow-ups. The system never submits applications; this is prep-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings, get_settings, load_profile
from .db import counts_by_status, jobs_for_report, list_companies, log_event
from .models import Company, Job
from .utils import slug, write_text


@dataclass
class ReportPaths:
    stamped: Path
    latest: Path


def write_opportunities_report(
    settings: Settings | None = None,
    *,
    limit: int = 500,
    strong_min: float = 0.55,
    watch_min: float = 0.28,
    min_score: float = 0.0,
) -> ReportPaths:
    """Write ``data/reports/opportunities_*.md`` and overwrite ``latest.md``."""
    s = settings or get_settings()
    s.paths.reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%SUTC")
    stamped = s.paths.reports_dir / f"opportunities_{stamp}.md"
    latest = s.paths.reports_dir / "latest.md"

    jobs = jobs_for_report(limit=limit)
    companies = {c.slug: c for c in list_companies()}

    filtered = [
        j
        for j in jobs
        if j.match_score is None or j.match_score >= min_score
    ]

    strong = [j for j in filtered if (j.match_score or 0) >= strong_min]
    watch = [
        j
        for j in filtered
        if watch_min <= (j.match_score or 0) < strong_min
    ]
    backlog = [
        j
        for j in filtered
        if j.match_score is not None and (j.match_score or 0) < watch_min
    ]
    unscored = [j for j in filtered if j.match_score is None]

    profile = load_profile(s)
    basics = profile.get("basics", {}) or {}
    headline = basics.get("headline", "")

    counts = counts_by_status()
    body: list[str] = []

    body.append("# Job opportunities report\n")
    body.append(
        "_Preparation only — nothing is submitted anywhere. All data stays on your machine._\n"
    )
    body.append(f"**Generated:** {now.isoformat()}\n")
    if headline:
        body.append(f"**Profile:** {headline}\n")
    body.append("\n## Summary\n")
    body.append(f"- Jobs in database: **{len(jobs)}** (this report lists up to {limit})\n")
    body.append(f"- By status: `{counts}`\n")
    body.append(
        f"- **Strong** (score ≥ {strong_min}): {len(strong)} · "
        f"**Worth a look** ({watch_min}–{strong_min}): {len(watch)} · "
        f"**Lower / backlog** (< {watch_min}): {len(backlog)} · "
        f"**Not yet scored:** {len(unscored)}\n"
    )
    body.append("\n---\n")

    body.append("\n## Strong matches\n")
    body.extend(_table(s, strong))

    body.append("\n## Worth a look\n")
    body.extend(_table(s, watch))

    if backlog:
        body.append("\n## Lower priority (still in your database)\n")
        body.extend(_table(s, backlog[:80], max_rows=80))

    if unscored:
        body.append("\n## Not scored yet (run `python run.py match-all --status new`)\n")
        body.extend(_table(s, unscored[:50], max_rows=50))

    body.append("\n## Companies hiring (from this dataset)\n")
    body.extend(_company_rollup(filtered))

    body.append("\n## Company intel & contacts (local)\n")
    body.extend(_company_pipeline_table(s, companies, filtered))

    body.append("\n## Suggested next steps (manual)\n")
    body.extend(_checklist(s, strong, companies))

    body.append(
        "\n---\n\n_Open `data/reports/latest.md` after each `python run.py update` run._\n"
    )

    text = "\n".join(body)
    write_text(stamped, text)
    write_text(latest, text)

    log_event(
        "reporting",
        "report.written",
        {"stamped": str(stamped), "latest": str(latest), "n_jobs": len(filtered)},
    )
    return ReportPaths(stamped=stamped, latest=latest)


def _md_escape(cell: str) -> str:
    return (cell or "").replace("|", "\\|").replace("\n", " ").strip()


def _table(settings: Settings, jobs: list[Job], max_rows: int | None = None) -> list[str]:
    if not jobs:
        return ["_None in this band._\n"]
    rows = jobs if max_rows is None else jobs[:max_rows]
    lines = [
        "| Score | Company | Role | Location | Status | Link | Notes |",
        "|---:|---|---|---|---|---|---|",
    ]
    for j in rows:
        score = f"{j.match_score:.2f}" if j.match_score is not None else "—"
        reason = _read_reasoning(settings, j.id)
        lines.append(
            "| "
            + " | ".join(
                [
                    score,
                    _md_escape(j.company),
                    _md_escape((j.title or "")[:60]),
                    _md_escape((j.location or "")[:40]),
                    _md_escape(j.status),
                    f"[open]({j.url})" if j.url.startswith("http") else _md_escape(j.url),
                    _md_escape(reason[:120]),
                ]
            )
            + " |"
        )
    if max_rows is not None and len(jobs) > max_rows:
        lines.append(f"\n_…and {len(jobs) - max_rows} more not shown._\n")
    lines.append("")
    return lines


def _read_reasoning(settings: Settings, job_id: str) -> str:
    p = settings.paths.applications_dir / job_id / "match_score.json"
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("reasoning", "") or "")
    except (json.JSONDecodeError, OSError):
        return ""


def _company_rollup(jobs: list[Job]) -> list[str]:
    by: dict[str, list[Job]] = {}
    for j in jobs:
        key = (j.company or "Unknown").strip() or "Unknown"
        by.setdefault(key, []).append(j)
    items = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    lines = ["| Company | Open roles | Best score |", "|---|---:|---:|"]
    for name, jlist in items[:40]:
        scores = [x.match_score for x in jlist if x.match_score is not None]
        best = f"{max(scores):.2f}" if scores else "—"
        lines.append(f"| {_md_escape(name)} | {len(jlist)} | {best} |")
    lines.append("")
    return lines


def _company_pipeline_table(
    settings: Settings,
    companies: dict[str, Company],
    jobs: list[Job],
) -> list[str]:
    """Map company names from jobs to brief/contacts on disk."""
    lines = [
        "| Company | Brief | Contacts |",
        "|---|---|---|",
    ]
    seen: set[str] = set()
    for j in jobs:
        name = (j.company or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        sl = slug(name)
        brief = settings.paths.companies_dir / sl / "brief.md"
        contacts = settings.paths.companies_dir / sl / "contacts.csv"
        brief_cell = f"`{brief.name}`" if brief.exists() else "— run `brief \"…\"`"
        cont_cell = f"`{contacts.name}`" if contacts.exists() else "— optional"
        key = sl
        if key in companies and companies[key].brief_path:
            bp = Path(companies[key].brief_path)
            if bp.exists():
                brief_cell = f"[brief]({bp.as_posix()})"
        lines.append(f"| {_md_escape(name)} | {brief_cell} | {cont_cell} |")
        if len(seen) >= 60:
            break
    lines.append("")
    return lines


def _checklist(
    settings: Settings,
    strong: list[Job],
    companies: dict[str, Company],
) -> list[str]:
    todos: list[str] = []
    for j in strong[:15]:
        sl = slug(j.company or "")
        brief = settings.paths.companies_dir / sl / "brief.md"
        if not brief.exists():
            todos.append(
                f"- [ ] Company brief: `python run.py brief \"{j.company}\"`"
            )
    if not todos:
        todos.append("- [ ] Pick 2–3 roles from **Strong matches** and open the links.")
    todos.append("- [ ] For shortlists only: add names → `python run.py contacts \"Co\" -n \"Name (Title)\"`")
    todos.append("- [ ] When you apply, track the decision yourself (this tool does not auto-apply).")
    return [t + "\n" for t in todos]
