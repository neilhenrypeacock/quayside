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

    _scheduler.start()
    logger.info("Scheduler started — pipeline will run Mon–Fri every 10 min, 07:00–17:00 UTC")

    with app.app_context():
        pass  # ensure app context available if needed later
