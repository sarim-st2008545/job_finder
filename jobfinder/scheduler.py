"""APScheduler wrapper for periodic scans + auto-match.

Runs the Job-Scanner Agent every N hours and the Matcher on any new jobs. Stops
on Ctrl-C. For a fully detached daemon, run via cron / Task Scheduler instead.
"""

from __future__ import annotations

import signal
import time

from apscheduler.schedulers.background import BackgroundScheduler

from .agents import JobScannerAgent, MatcherAgent
from .db import list_jobs
from .logging_setup import get_logger


def run_scheduler(scan_every_hours: float = 4.0, match_new: bool = True) -> None:
    log = get_logger("scheduler")

    def job() -> None:
        log.info("Tick: scanning…")
        scanner = JobScannerAgent()
        ingested = scanner.run()
        log.info("Tick: scanned %d job(s)", len(ingested))
        if match_new:
            matcher = MatcherAgent()
            for j in list_jobs(status="new", limit=200):
                try:
                    matcher.run(j.id)
                except Exception as e:
                    log.exception("Match failed for %s: %s", j.id, e)
        try:
            from .reporting import write_opportunities_report

            paths = write_opportunities_report()
            log.info("Tick: report → %s", paths.latest)
        except Exception as e:
            log.warning("Tick: report failed: %s", e)

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(job, "interval", hours=scan_every_hours, next_run_time=_now_plus(seconds=2))
    sched.start()
    log.info("Scheduler started: every %s hour(s). Ctrl-C to stop.", scan_every_hours)

    stop = {"flag": False}

    def _handler(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handler)
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (AttributeError, ValueError):
        pass  # not available on all platforms

    try:
        while not stop["flag"]:
            time.sleep(1)
    finally:
        sched.shutdown(wait=False)
        log.info("Scheduler stopped.")


def _now_plus(seconds: int):
    from datetime import datetime, timedelta

    return datetime.utcnow() + timedelta(seconds=seconds)
