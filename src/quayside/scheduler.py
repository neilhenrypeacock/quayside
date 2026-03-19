"""Background scheduler — runs the scrape pipeline daily on weekdays.

Uses APScheduler so the pipeline runs inside the existing web process on Railway,
sharing the same SQLite DB and filesystem. Only starts the scheduler once; gunicorn
must use a single worker to avoid duplicate runs.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

_scheduler = None


def run_and_log_quality_check() -> None:
    """Run quality checks and log results to error_log for the error dashboard."""
    from quayside.db import clear_stale_errors, insert_error_log
    from quayside.quality import run_quality_checks

    today = date.today().isoformat()
    logger.info("Error scan: running quality checks for %s", today)

    try:
        result = run_quality_checks(today)
    except Exception:
        logger.exception("Error scan: quality checks failed")
        return

    # Transform quality issues into error_log entries
    entries = []
    for issue in result.get("issues", []):
        # Map severity: quality.py uses 'warn', error_log uses 'warning'
        severity = "warning" if issue["severity"] == "warn" else issue["severity"]

        # Build detail string from available fields
        detail_parts = []
        if issue.get("message"):
            detail_parts.append(issue["message"])
        if issue.get("grade"):
            detail_parts.append(f"Grade: {issue['grade']}")
        if issue.get("value") is not None:
            detail_parts.append(f"Value: {issue['value']}")
        if issue.get("expected") is not None:
            detail_parts.append(f"Expected: {issue['expected']}")
        if issue.get("date"):
            detail_parts.append(f"Date: {issue['date']}")

        entries.append({
            "check_name": issue["check_type"],
            "severity": severity,
            "port": issue.get("port"),
            "species": issue.get("species"),
            "detail": " · ".join(detail_parts) if detail_parts else None,
        })

    insert_error_log(entries)
    clear_stale_errors()

    error_count = sum(1 for e in entries if e["severity"] == "error")
    warn_count = sum(1 for e in entries if e["severity"] == "warning")
    logger.info("Error scan complete: %d errors, %d warnings", error_count, warn_count)


def _run_pipeline_if_needed() -> None:
    """Run the pipeline only if we haven't already produced today's digest."""
    from quayside.db import get_latest_date

    # Only run Mon–Fri, 07:00–17:00 UTC
    now_utc = datetime.utcnow()
    if now_utc.weekday() >= 5:
        logger.debug("Scheduler: weekend, skipping")
        return
    if not (7 <= now_utc.hour < 17):
        logger.debug("Scheduler: outside 07:00–17:00 UTC, skipping")
        return

    today = date.today().isoformat()
    latest = get_latest_date()
    if latest == today:
        logger.debug("Scheduler: already have data for %s, skipping", today)
        return

    logger.info("Scheduler: starting pipeline for %s", today)
    try:
        from quayside.run import main
        main()
    except Exception:
        logger.exception("Scheduler: pipeline failed")


def start_scheduler(app) -> None:
    """Start the APScheduler background scheduler attached to the Flask app.

    Safe to call multiple times — only starts once per process.
    """
    global _scheduler

    if _scheduler is not None:
        return

    # Don't run in Flask's reloader child process
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler not installed — scheduled pipeline disabled")
        return

    _scheduler = BackgroundScheduler(daemon=True)

    # Run every 10 minutes; time-of-day + weekend guard is inside _run_pipeline_if_needed
    _scheduler.add_job(
        _run_pipeline_if_needed,
        "interval",
        minutes=10,
        id="pipeline_10min",
        name="Scrape pipeline (every 10 min, 07:00–17:00 UTC Mon–Fri)",
        replace_existing=True,
    )

    # Error scan: run quality checks hourly on weekdays 8am–5pm
    _scheduler.add_job(
        run_and_log_quality_check,
        trigger="cron",
        day_of_week="mon-fri",
        hour="8-17",
        minute=0,
        id="error_scan",
        name="Error scan (hourly, 08:00–17:00 UTC Mon–Fri)",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started — pipeline every 10 min + error scan hourly, Mon–Fri")

    with app.app_context():
        pass  # ensure app context available if needed later
