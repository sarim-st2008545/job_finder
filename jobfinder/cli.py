"""Typer-based CLI.

Run via the project-root `run.py`:

    python run.py --help
    python run.py init
    python run.py update            # scan → match new → opportunities report (main entry)
    python run.py report            # regenerate report from DB only
    python run.py scan
    python run.py match-all
    python run.py match <job_id>
    python run.py add-job <url>
    python run.py brief "Acme AI"
    python run.py contacts "Acme AI" --names "Jane Doe (CTO)"
    python run.py status
    python run.py schedule --every 4
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .agents import (
    CompanyResearchAgent,
    ContactFinderAgent,
    JobScannerAgent,
    MatcherAgent,
)
from .config import PROJECT_ROOT, get_settings
from .db import (
    counts_by_status,
    get_job,
    list_jobs,
    recent_events,
)
from .logging_setup import setup_logging
from .reporting import write_opportunities_report
from .sources import build_source


app = typer.Typer(add_completion=False, help="Local-first agentic job-search system.")
console = Console()


# ---------- init ----------


@app.command()
def init(
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files."),
) -> None:
    """Bootstrap profile.yaml and .env from examples."""
    setup_logging()
    settings = get_settings()

    profile_dst = settings.paths.profile_path
    profile_src = profile_dst.with_name("profile.example.yaml")
    if profile_src.exists() and (overwrite or not profile_dst.exists()):
        shutil.copyfile(profile_src, profile_dst)
        console.print(f"[green]Wrote[/] {profile_dst}")
    else:
        console.print(f"Profile already exists at {profile_dst} (use --overwrite).")

    env_dst = PROJECT_ROOT / ".env"
    env_src = PROJECT_ROOT / ".env.example"
    if env_src.exists() and (overwrite or not env_dst.exists()):
        shutil.copyfile(env_src, env_dst)
        console.print(f"[green]Wrote[/] {env_dst} — edit it to choose your LLM provider.")
    else:
        console.print(f".env already exists at {env_dst} (use --overwrite).")

    settings.paths.ensure()
    console.print("[bold green]init complete.[/]")
    console.print(
        "[dim]Next:[/] edit profile → `python run.py update` → open [cyan]data/reports/latest.md[/]"
    )


# ---------- refresh pipeline: scan + match + report ----------


@app.command("update")
def cmd_update(
    scan_: bool = typer.Option(True, "--scan/--no-scan", help="Run Job-Scanner first."),
    match_: bool = typer.Option(True, "--match/--no-match", help="Score jobs in --match-status."),
    match_status: str = typer.Option(
        "new",
        "--match-status",
        help="Only these jobs are scored (e.g. new, scored to re-run).",
    ),
    match_limit: int = typer.Option(200, "--match-limit"),
    report_limit: int = typer.Option(500, "--report-limit"),
    min_score: float = typer.Option(0.0, "--min-score", help="Hide jobs below this score in report."),
    strong: float = typer.Option(0.55, "--strong"),
    watch: float = typer.Option(0.28, "--watch"),
) -> None:
    """Scan sources, score new leads, write `data/reports/latest.md` — prep only, no submissions."""
    setup_logging()
    if scan_:
        scanner = JobScannerAgent()
        ingested = scanner.run()
        console.print(f"[bold]Scan:[/] ingested {len(ingested)} job(s) this run.")
    if match_:
        matcher = MatcherAgent()
        jobs = list_jobs(status=match_status, limit=match_limit)
        if not jobs:
            console.print(f"[dim]Match:[/] no jobs with status={match_status}.")
        for j in jobs:
            console.print(f"  → score [cyan]{j.id}[/] {j.title[:50]}…")
            try:
                matcher.run(j.id)
            except Exception as e:
                console.print(f"    [red]failed:[/] {e}")
    paths = write_opportunities_report(
        limit=report_limit,
        min_score=min_score,
        strong_min=strong,
        watch_min=watch,
    )
    console.print(f"[bold green]Report ready[/] → {paths.latest}")


@app.command()
def report(
    limit: int = typer.Option(500, "--limit"),
    min_score: float = typer.Option(0.0, "--min-score"),
    strong: float = typer.Option(0.55, "--strong"),
    watch: float = typer.Option(0.28, "--watch"),
) -> None:
    """Regenerate the opportunities report from SQLite (no scan, no API calls)."""
    setup_logging()
    paths = write_opportunities_report(
        limit=limit,
        min_score=min_score,
        strong_min=strong,
        watch_min=watch,
    )
    console.print(f"[green]Wrote[/] {paths.stamped}\n[green]Latest[/]   {paths.latest}")


# ---------- scan ----------


@app.command()
def scan() -> None:
    """Run the Job-Scanner Agent across all enabled sources."""
    setup_logging()
    agent = JobScannerAgent()
    jobs = agent.run()
    console.print(f"[bold]Ingested[/] {len(jobs)} job(s).")
    _print_jobs_table(jobs[:20])


@app.command("add-job")
def add_job(
    url: Optional[str] = typer.Argument(None, help="Job URL to ingest."),
    text_file: Optional[Path] = typer.Option(None, "--text-file", help="Path to a text file with the JD."),
    title: str = typer.Option("Manually added job", "--title"),
    company: str = typer.Option("Unknown", "--company"),
) -> None:
    """Add a single job manually (URL or pasted JD text)."""
    setup_logging()
    jd_text = text_file.read_text(encoding="utf-8") if text_file else None
    source = build_source("manual", url=url, jd_text=jd_text, title=title, company=company)
    if source is None:
        raise typer.BadParameter("manual source not available")
    agent = JobScannerAgent()
    # Bypass the YAML by injecting an enabled override
    jobs = agent.run(
        source_overrides=[
            {
                "name": "manual",
                "enabled": True,
                "url": url,
                "jd_text": jd_text,
                "title": title,
                "company": company,
            }
        ]
    )
    if jobs:
        console.print(f"[green]Added[/] job id={jobs[0].id}")
    else:
        console.print("[yellow]Nothing was added.[/]")


# ---------- match ----------


@app.command()
def match(
    job_id: str = typer.Argument(..., help="Job id from `python run.py list`"),
) -> None:
    """Run the Match & Draft Agent on a single job."""
    setup_logging()
    agent = MatcherAgent()
    result = agent.run(job_id)
    if not result:
        raise typer.Exit(1)
    console.print(
        f"[bold]Score[/]: {result.final_score:.2f} "
        f"(kw={result.keyword_score:.2f}, llm={result.llm_score:.2f}) "
        f"variant=[cyan]{result.recommended_variant}[/]"
    )
    if result.reasoning:
        console.print(f"[dim]{result.reasoning}[/]")


@app.command("match-all")
def match_all(
    status: str = typer.Option("new", help="Only match jobs in this status."),
    limit: int = typer.Option(50, help="Max jobs to process."),
) -> None:
    """Run the Match & Draft Agent on every job in the given status."""
    setup_logging()
    agent = MatcherAgent()
    jobs = list_jobs(status=status, limit=limit)
    if not jobs:
        console.print(f"No jobs with status={status}.")
        return
    for j in jobs:
        console.print(f"-> matching [cyan]{j.id}[/]: {j.title} @ {j.company}")
        try:
            agent.run(j.id)
        except Exception as e:
            console.print(f"  [red]failed:[/] {e}")


# ---------- company brief & contacts ----------


@app.command()
def brief(
    company: str = typer.Argument(..., help="Company name."),
    domain: Optional[str] = typer.Option(None, "--domain", help="Optional override."),
) -> None:
    """Run the Company-R&D Agent and produce data/companies/<slug>/brief.md."""
    setup_logging()
    agent = CompanyResearchAgent()
    result = agent.run(company, domain=domain)
    console.print(
        f"[green]Brief written:[/] {result.brief_path}  "
        f"([cyan]{len(result.sources)}[/] sources)"
    )


@app.command()
def contacts(
    company: str = typer.Argument(..., help="Company name."),
    domain: Optional[str] = typer.Option(None, "--domain"),
    names: list[str] = typer.Option(
        [],
        "--names",
        "-n",
        help='Seed names like "Jane Doe (Head of AI)". Repeat for multiple.',
    ),
    no_mx: bool = typer.Option(False, "--no-mx", help="Skip DNS MX validation."),
) -> None:
    """Generate likely email candidates for known names at a company."""
    setup_logging()
    seeds: list[tuple[str, str | None]] = []
    for raw in names:
        if "(" in raw and raw.endswith(")"):
            name, title = raw[: raw.rfind("(")].strip(), raw[raw.rfind("(") + 1 : -1].strip()
            seeds.append((name, title))
        else:
            seeds.append((raw.strip(), None))
    agent = ContactFinderAgent()
    out = agent.run(company, domain=domain, seed_names=seeds, validate_mx=not no_mx)
    console.print(f"[green]Wrote[/] {len(out)} contact candidate(s).")


# ---------- status / list ----------


@app.command()
def status() -> None:
    """Show queue counts and recent agent events."""
    setup_logging()
    counts = counts_by_status()
    console.print("[bold]Jobs by status[/]:")
    for k, v in counts.items():
        console.print(f"  {k:>18} : {v}")
    console.print("\n[bold]Recent events[/]:")
    for ev in recent_events(limit=10):
        console.print(
            f"  [dim]{ev['ts']}[/] [cyan]{ev['agent']:>16}[/] {ev['event']} "
            f"{json.dumps(ev['payload'])[:120]}"
        )


@app.command("list")
def list_cmd(
    status_filter: Optional[str] = typer.Option(None, "--status"),
    limit: int = typer.Option(25, "--limit"),
) -> None:
    """List jobs."""
    setup_logging()
    jobs = list_jobs(status=status_filter, limit=limit)
    _print_jobs_table(jobs)


@app.command()
def show(job_id: str) -> None:
    """Show one job and its application paths."""
    setup_logging()
    job = get_job(job_id)
    if not job:
        console.print("[red]not found[/]")
        raise typer.Exit(1)
    console.print_json(json.dumps(job.model_dump(), default=str))
    app_dir = get_settings().paths.applications_dir / job_id
    if app_dir.exists():
        console.print(f"\n[bold]Application files[/] @ {app_dir}")
        for p in sorted(app_dir.iterdir()):
            console.print(f"  - {p.name}")


# ---------- scheduler ----------


@app.command()
def schedule(
    every: float = typer.Option(4.0, "--every", help="Hours between scans."),
    no_match: bool = typer.Option(False, "--no-match", help="Skip auto-match step."),
) -> None:
    """Run continuously: scan then match every N hours."""
    setup_logging()
    from .scheduler import run_scheduler

    run_scheduler(scan_every_hours=every, match_new=not no_match)


# ---------- internal helpers ----------


def _print_jobs_table(jobs) -> None:
    if not jobs:
        console.print("[dim]no jobs[/]")
        return
    t = Table()
    for col in ("id", "score", "status", "source", "title", "company", "location"):
        t.add_column(col)
    for j in jobs:
        score = f"{j.match_score:.2f}" if j.match_score is not None else "-"
        t.add_row(
            j.id,
            score,
            j.status,
            j.source,
            (j.title or "")[:48],
            (j.company or "")[:32],
            (j.location or "")[:24],
        )
    console.print(t)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
