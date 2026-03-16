"""Background scheduler — runs the scrape pipeline daily on weekdays.

Uses APScheduler so the pipeline runs inside the existing web process on Railway,
sharing the same SQLite DB and filesystem. Only starts the scheduler once; gunicorn
must use a single worker to avoid duplicate runs.
"""

from __future__ import annotations

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

_scheduler = None


def _run_pipeline_if_needed() -> None:
    """Run the pipeline only if we haven't already produced today's digest."""
    from pathlib import Path

    from quayside.db import get_latest_date

    today = date.today().isoformat()

    # Skip weekends (Mon=0 ... Sun=6)
    if date.today().weekday() >= 5:
        logger.debug("Scheduler: weekend, skipping")
        return

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
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("APScheduler not installed — scheduled pipeline disabled")
        return

    _scheduler = BackgroundScheduler(daemon=True)

    # Run at 10:15 AM UTC Mon–Fri, and also every 30 min as a catch-up check
    _scheduler.add_job(
        _run_pipeline_if_needed,
        CronTrigger(day_of_week="mon-fri", hour=10, minute=15),
        id="pipeline_daily",
        name="Daily scrape pipeline",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_pipeline_if_needed,
        "interval",
        minutes=30,
        id="pipeline_catchup",
        name="Pipeline catch-up check",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started — pipeline will run Mon–Fri at 10:15 UTC")

    with app.app_context():
        pass  # ensure app context available if needed later
