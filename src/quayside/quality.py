"""Data quality checks for Quayside.

Runs five checks against the prices table and writes issues to quality_log.
Designed to run 3× daily (09:30, 13:30, 17:30) via systemd timer.

Usage:
    python -m quayside.quality
"""

from __future__ import annotations

import logging
import math
from datetime import date as date_type
from datetime import datetime, timedelta

from quayside.db import get_connection, init_db

logger = logging.getLogger(__name__)

# Active ports to monitor (exclude Demo Port)
_ACTIVE_PORTS_SQL = """
    SELECT name FROM ports WHERE status = 'active' AND name != 'Demo Port'
"""

# Thresholds
_OUTLIER_ERROR_SIGMA = 5.0   # price > mean + 5σ → error
_OUTLIER_WARN_SIGMA = 3.0    # price > mean + 3σ → warn
_MIN_HISTORY_RECORDS = 10    # min records in 30-day history to run outlier check
_RECORD_COUNT_WARN_RATIO = 0.4   # today's count < 40% of median → warn
_DAY_AVG_WARN_PCT = 50.0     # port day avg ±50% of rolling avg → warn
_DAY_AVG_ERROR_PCT = 100.0   # port day avg ±100% of rolling avg → error
_STALE_WARN_DAYS = 2         # trading days without data → warn
_STALE_ERROR_DAYS = 4        # trading days without data → error
_SEEDED_TIMESTAMP = "20:03:12.760850"  # known seeded-data timestamp fragment


def run_quality_checks(date: str | None = None) -> dict:
    """Run all checks for `date` (defaults to today). Writes to quality_log.

    Returns summary dict: {errors, warns, issues: [...]}.
    """
    init_db()
    conn = get_connection()

    if date is None:
        date = date_type.today().isoformat()

    checked_at = datetime.utcnow().isoformat()
    issues: list[dict] = []

    active_ports = [r[0] for r in conn.execute(_ACTIVE_PORTS_SQL).fetchall()]

    issues.extend(_check_outlier_prices(conn, date, checked_at, active_ports))
    issues.extend(_check_record_count(conn, date, checked_at, active_ports))
    issues.extend(_check_stale_data(conn, date, checked_at, active_ports))
    issues.extend(_check_day_avg_spike(conn, date, checked_at, active_ports))
    issues.extend(_check_seeded_data(conn, date, checked_at, active_ports))

    # Write all issues to quality_log
    conn.executemany(
        """INSERT INTO quality_log
           (checked_at, check_type, severity, port, date, species, grade, value, expected, message)
           VALUES (:checked_at, :check_type, :severity, :port, :date, :species, :grade, :value, :expected, :message)""",
        issues,
    )
    conn.commit()
    conn.close()

    errors = sum(1 for i in issues if i["severity"] == "error")
    warns = sum(1 for i in issues if i["severity"] == "warn")
    return {"errors": errors, "warns": warns, "issues": issues}


# ── Check 1: Per-record outlier prices ───────────────────────────────────────

def _check_outlier_prices(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag prices that are statistical outliers vs. 30-day rolling history."""
    issues = []
    cutoff_30d = (datetime.fromisoformat(date) - timedelta(days=30)).date().isoformat()

    for port in active_ports:
        # Get today's records
        today_rows = conn.execute(
            """SELECT species, grade, price_avg FROM prices
               WHERE port = ? AND date = ? AND price_avg IS NOT NULL""",
            (port, date),
        ).fetchall()

        if not today_rows:
            continue

        # Compute per-species/grade stats over last 30 days (excluding today)
        history = conn.execute(
            """SELECT species, grade, AVG(price_avg), COUNT(*),
                      AVG(price_avg * price_avg) - AVG(price_avg) * AVG(price_avg)
               FROM prices
               WHERE port = ? AND date > ? AND date < ? AND price_avg IS NOT NULL
               GROUP BY species, grade
               HAVING COUNT(*) >= ?""",
            (port, cutoff_30d, date, _MIN_HISTORY_RECORDS),
        ).fetchall()

        stats: dict[tuple, tuple] = {}
        for species, grade, mean, count, variance in history:
            stddev = math.sqrt(max(variance, 0))
            stats[(species, grade)] = (mean, stddev)

        for species, grade, price_avg in today_rows:
            if (species, grade) not in stats:
                continue
            mean, stddev = stats[(species, grade)]
            if stddev == 0:
                continue
            z = (price_avg - mean) / stddev
            if z > _OUTLIER_ERROR_SIGMA:
                issues.append(_issue(
                    checked_at, "outlier_price", "error", port, date, species, grade,
                    value=round(price_avg, 2), expected=round(mean, 2),
                    message=f"{species} {grade} at {port}: £{price_avg:.2f}/kg is {z:.1f}σ above 30-day mean (£{mean:.2f}/kg)",
                ))
            elif z > _OUTLIER_WARN_SIGMA:
                issues.append(_issue(
                    checked_at, "outlier_price", "warn", port, date, species, grade,
                    value=round(price_avg, 2), expected=round(mean, 2),
                    message=f"{species} {grade} at {port}: £{price_avg:.2f}/kg is {z:.1f}σ above 30-day mean (£{mean:.2f}/kg)",
                ))

    return issues


# ── Check 2: Record count anomaly ────────────────────────────────────────────

def _check_record_count(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag if today's record count is unusually low vs. the port's rolling median."""
    issues = []

    for port in active_ports:
        today_count = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE port = ? AND date = ?", (port, date)
        ).fetchone()[0]

        # Get last 20 trading-day counts (excluding today)
        prior_counts = conn.execute(
            """SELECT COUNT(*) as n FROM prices
               WHERE port = ? AND date < ?
               GROUP BY date ORDER BY date DESC LIMIT 20""",
            (port, date),
        ).fetchall()

        if len(prior_counts) < 5:
            continue  # not enough history

        sorted_counts = sorted(r[0] for r in prior_counts)
        median = _median(sorted_counts)
        if median == 0:
            continue

        if today_count == 0:
            issues.append(_issue(
                checked_at, "record_count", "error", port, date,
                value=0, expected=median,
                message=f"{port}: 0 records today — expected ~{median:.0f} based on recent history",
            ))
        elif today_count < median * _RECORD_COUNT_WARN_RATIO:
            issues.append(_issue(
                checked_at, "record_count", "warn", port, date,
                value=today_count, expected=median,
                message=f"{port}: only {today_count} records today vs. typical ~{median:.0f} ({today_count/median*100:.0f}% of normal)",
            ))

    return issues


# ── Check 3: Stale data ───────────────────────────────────────────────────────

def _check_stale_data(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag ports not updated within the expected number of trading days."""
    issues = []
    today = datetime.fromisoformat(date).date()

    for port in active_ports:
        row = conn.execute(
            "SELECT MAX(date) FROM prices WHERE port = ?", (port,)
        ).fetchone()
        if not row or not row[0]:
            continue

        last_date = date_type.fromisoformat(row[0])
        trading_gap = _trading_days_between(last_date, today)

        if trading_gap >= _STALE_ERROR_DAYS:
            issues.append(_issue(
                checked_at, "stale_data", "error", port, date,
                value=trading_gap,
                message=f"{port}: no data for {trading_gap} trading days (last: {last_date})",
            ))
        elif trading_gap >= _STALE_WARN_DAYS:
            issues.append(_issue(
                checked_at, "stale_data", "warn", port, date,
                value=trading_gap,
                message=f"{port}: no data for {trading_gap} trading days (last: {last_date})",
            ))

    return issues


# ── Check 4: Day average spike ───────────────────────────────────────────────

def _check_day_avg_spike(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag if a port's daily average price deviates sharply from its 30-day rolling average."""
    issues = []
    cutoff_30d = (datetime.fromisoformat(date) - timedelta(days=30)).date().isoformat()

    for port in active_ports:
        today_avg = conn.execute(
            "SELECT AVG(price_avg) FROM prices WHERE port = ? AND date = ? AND price_avg IS NOT NULL",
            (port, date),
        ).fetchone()[0]

        if today_avg is None:
            continue

        rolling_avg = conn.execute(
            """SELECT AVG(day_avg) FROM (
                   SELECT AVG(price_avg) as day_avg FROM prices
                   WHERE port = ? AND date > ? AND date < ? AND price_avg IS NOT NULL
                   GROUP BY date
               )""",
            (port, cutoff_30d, date),
        ).fetchone()[0]

        if rolling_avg is None or rolling_avg == 0:
            continue

        pct_change = abs(today_avg - rolling_avg) / rolling_avg * 100

        if pct_change >= _DAY_AVG_ERROR_PCT:
            issues.append(_issue(
                checked_at, "day_avg_spike", "error", port, date,
                value=round(today_avg, 2), expected=round(rolling_avg, 2),
                message=f"{port}: today's avg £{today_avg:.2f}/kg is {pct_change:.0f}% from 30-day rolling avg (£{rolling_avg:.2f}/kg)",
            ))
        elif pct_change >= _DAY_AVG_WARN_PCT:
            issues.append(_issue(
                checked_at, "day_avg_spike", "warn", port, date,
                value=round(today_avg, 2), expected=round(rolling_avg, 2),
                message=f"{port}: today's avg £{today_avg:.2f}/kg is {pct_change:.0f}% from 30-day rolling avg (£{rolling_avg:.2f}/kg)",
            ))

    return issues


# ── Check 5: Seeded demo data guard ──────────────────────────────────────────

def _check_seeded_data(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag any records with the known seeded-data timestamp still present on live ports."""
    issues = []

    for port in active_ports:
        count = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE port = ? AND scraped_at LIKE ?",
            (port, f"%{_SEEDED_TIMESTAMP}%"),
        ).fetchone()[0]

        if count:
            issues.append(_issue(
                checked_at, "seeded_data", "error", port, date,
                value=count,
                message=f"{port}: {count} records with seeded-data timestamp — likely a DB restore from a pre-cleanup backup",
            ))

    return issues


# ── Helpers ───────────────────────────────────────────────────────────────────

def _issue(
    checked_at: str,
    check_type: str,
    severity: str,
    port: str,
    date: str,
    species: str | None = None,
    grade: str | None = None,
    value: float | None = None,
    expected: float | None = None,
    message: str = "",
) -> dict:
    return {
        "checked_at": checked_at,
        "check_type": check_type,
        "severity": severity,
        "port": port,
        "date": date,
        "species": species,
        "grade": grade,
        "value": value,
        "expected": expected,
        "message": message,
    }


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    return sorted_values[mid] if n % 2 else (sorted_values[mid - 1] + sorted_values[mid]) / 2


def _trading_days_between(start: date_type, end: date_type) -> int:
    """Count weekdays (Mon–Fri) strictly between start and end (exclusive of start)."""
    count = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:  # Mon=0 … Fri=4
            count += 1
        current += timedelta(days=1)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = run_quality_checks()
    print(f"Quality check complete: {summary['errors']} errors, {summary['warns']} warnings")
    for issue in summary["issues"]:
        level = "ERROR" if issue["severity"] == "error" else "WARN "
        print(f"  [{level}] {issue['message']}")
