"""Data quality checks for Quayside.

Runs five checks against the prices table and writes issues to quality_log.
Designed to run 3× daily (10:00, 13:00, 16:00) via systemd timer.

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


# ── Comprehensive report ──────────────────────────────────────────────────────

def build_comprehensive_report(date: str | None = None) -> dict:
    """Build a full data quality report for `date` (defaults to today).

    Returns a dict with four sections:
      - port_dashboards: what each port dashboard will display
      - digest_preview: what the daily digest will contain
      - ops_health: ops dashboard health summary
      - quality_issues: all quality_log issues for the last 7 days
    """
    if date is None:
        date = date_type.today().isoformat()

    generated_at = datetime.utcnow().isoformat()
    conn = get_connection()
    active_ports = [r[0] for r in conn.execute(_ACTIVE_PORTS_SQL).fetchall()]

    result = {
        "date": date,
        "generated_at": generated_at,
        "port_dashboards": _report_port_dashboards(conn, date, active_ports),
        "digest_preview": _report_digest_preview(date, active_ports),
        "ops_health": _report_ops_health(conn, date, active_ports),
        "quality_issues": _report_quality_issues(conn),
    }
    conn.close()
    return result


def _report_port_dashboards(conn, date: str, active_ports: list[str]) -> list[dict]:
    """Re-compute hero stats for each port to preview what the dashboard shows."""
    from quayside.db import get_same_day_last_week, get_market_averages_for_date
    from quayside.species import normalise_species

    market = get_market_averages_for_date(date)
    results = []

    for port in sorted(active_ports):
        rows = conn.execute(
            "SELECT species, grade, price_avg FROM prices WHERE port=? AND date=? AND price_avg IS NOT NULL",
            (port, date),
        ).fetchall()

        record_count = len(rows)
        has_today_data = record_count > 0

        # Compute today's avg
        avg_prices = [r[2] for r in rows]
        today_avg = round(sum(avg_prices) / len(avg_prices), 2) if avg_prices else None

        # Vs last same weekday
        last_week_prices = get_same_day_last_week(port, date)
        history_days = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE port=? AND date < ?", (port, date)
        ).fetchone()[0]

        hero_vs_last_week = None
        hero_last_week_price = None
        if last_week_prices and avg_prices:
            lw_avgs = [v["price_avg"] for v in last_week_prices.values() if v["price_avg"]]
            if lw_avgs:
                lw_overall = sum(lw_avgs) / len(lw_avgs)
                today_overall = sum(avg_prices) / len(avg_prices)
                if lw_overall > 0:
                    hero_vs_last_week = round(((today_overall - lw_overall) / lw_overall) * 100, 1)
                hero_last_week_price = round(lw_overall, 2)

        # Vs market avg (for species this port sells, with ≥2 ports)
        canonical_species = {normalise_species(r[0]) for r in rows}
        market_avgs = [
            info["avg"] for canon, info in market.items()
            if info.get("avg") and canon in canonical_species and info.get("port_count", 0) >= 2
        ]
        hero_vs_market = None
        if market_avgs and avg_prices:
            market_overall = sum(market_avgs) / len(market_avgs)
            port_overall = sum(avg_prices) / len(avg_prices)
            if market_overall > 0:
                hero_vs_market = round(((port_overall - market_overall) / market_overall) * 100, 1)

        # This week / this month averages (last 5 / last 20 trading days)
        prior_days = conn.execute(
            """SELECT date, AVG(price_avg) as day_avg FROM prices
               WHERE port=? AND date < ? AND price_avg IS NOT NULL
               GROUP BY date ORDER BY date DESC""",
            (port, date),
        ).fetchall()
        prior_day_avgs = {r[0]: r[1] for r in prior_days}

        all_days = sorted(prior_day_avgs.keys(), reverse=True)
        if has_today_data and today_avg:
            all_days_with_today = [date] + all_days
        else:
            all_days_with_today = all_days

        def _period_avg(days):
            prices = []
            for d in days:
                if d == date:
                    prices.extend(avg_prices)
                else:
                    # approximate using day avg (we don't have all records in memory)
                    if d in prior_day_avgs:
                        prices.append(prior_day_avgs[d])
            return round(sum(prices) / len(prices), 2) if prices else None

        this_week_avg = _period_avg(all_days_with_today[:5])
        this_month_avg = _period_avg(all_days_with_today[:20])

        # Species without market benchmark (only 1 port sells them)
        no_benchmark = sorted([
            normalise_species(r[0]) for r in rows
            if market.get(normalise_species(r[0]), {}).get("port_count", 0) < 2
        ])
        # Deduplicate
        no_benchmark = sorted(set(no_benchmark))

        # Classify hero stat nulls
        hero_nulls = []
        if today_avg is None:
            hero_nulls.append("today_avg")
        if hero_vs_last_week is None:
            hero_nulls.append("vs_last_week")
        if hero_vs_market is None:
            hero_nulls.append("vs_market")

        # Is the vs_last_week null expected? (< 5 days of history = expected)
        hero_null_expected = history_days < 5

        results.append({
            "port": port,
            "has_today_data": has_today_data,
            "record_count": record_count,
            "today_avg": today_avg,
            "vs_last_week_pct": hero_vs_last_week,
            "last_week_price": hero_last_week_price,
            "this_week_avg": this_week_avg,
            "this_month_avg": this_month_avg,
            "vs_market_pct": hero_vs_market,
            "history_days": history_days,
            "hero_nulls": hero_nulls,
            "hero_null_expected": hero_null_expected,
            "species_no_benchmark": no_benchmark[:10],  # cap for display
        })

    return results


def _report_digest_preview(date: str, active_ports: list[str]) -> dict:
    """Summarise what the daily digest will show for `date`."""
    from pathlib import Path

    result: dict = {
        "ports_reporting": [],
        "missing_from_digest": [],
        "total_species": 0,
        "benchmark_species_available": 0,
        "benchmark_species_missing": [],
        "movers_count": 0,
        "top_mover": None,
        "digest_path": None,
        "digest_already_generated": False,
        "error": None,
    }

    try:
        from quayside.report import build_report_data, BENCHMARK_SPECIES
        data = build_report_data(date)

        result["ports_reporting"] = data.get("ports_reporting", [])
        result["missing_from_digest"] = [
            p for p in active_ports if p not in result["ports_reporting"]
        ]
        result["total_species"] = data.get("total_species", 0)

        # Benchmark coverage
        benchmark_snap = data.get("benchmark_snapshot", [])
        available_benchmarks = [b["species"] for b in benchmark_snap]
        result["benchmark_species_available"] = len(available_benchmarks)
        result["benchmark_species_missing"] = [
            s for s in BENCHMARK_SPECIES if s not in available_benchmarks
        ]

        # Movers
        movers = data.get("movers", [])
        result["movers_count"] = len(movers)
        if movers:
            top = movers[0]
            result["top_mover"] = {
                "species": top.get("species", ""),
                "port": top.get("port", ""),
                "change_pct": top.get("change_pct", 0),
            }

        # Check if digest HTML already generated
        from quayside.report import OUTPUT_DIR
        digest_path = OUTPUT_DIR / f"digest_{date}.html"
        result["digest_path"] = str(digest_path)
        result["digest_already_generated"] = digest_path.exists()

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _report_ops_health(conn, date: str, active_ports: list[str]) -> dict:
    """Summarise what the ops dashboard shows for today's pipeline health."""
    today_dt = datetime.fromisoformat(date).date()

    # Scrape log for today
    scrape_rows = conn.execute(
        """SELECT port, success, record_count, ran_at FROM scrape_log
           WHERE DATE(ran_at) = ? ORDER BY ran_at""",
        (date,),
    ).fetchall()

    ports_succeeded = sorted({r[0] for r in scrape_rows if r[1]})
    ports_attempted = sorted({r[0] for r in scrape_rows})
    ports_failed = sorted(set(ports_attempted) - set(ports_succeeded))

    # Coverage holes: ports with < 3 distinct dates in last 5 trading days
    cutoff = (today_dt - timedelta(days=9)).isoformat()  # ~2 weeks back covers 5+ trading days
    coverage_rows = conn.execute(
        """SELECT port, COUNT(DISTINCT date) as n FROM prices
           WHERE port != 'Demo Port' AND date >= ? AND date <= ?
           GROUP BY port""",
        (cutoff, date),
    ).fetchall()
    coverage_map = {r[0]: r[1] for r in coverage_rows}

    coverage_holes = [
        {"port": p, "days_in_recent": coverage_map.get(p, 0)}
        for p in active_ports
        if coverage_map.get(p, 0) < 3
    ]

    # Historical gap count (weekday dates in last 2 weeks with no data for any port)
    gap_count = conn.execute(
        """SELECT COUNT(DISTINCT date) FROM prices
           WHERE port != 'Demo Port' AND date >= date(?, '-14 days') AND date < ?""",
        (date, date),
    ).fetchone()[0]
    # Rough: 10 weekdays in 2 weeks, minus days with data
    historical_gap_count = max(0, 10 - gap_count)

    # Quality issues summary
    cutoff_7d = (datetime.utcnow() - timedelta(days=7)).isoformat()
    quality_counts = conn.execute(
        "SELECT severity, COUNT(*) FROM quality_log WHERE checked_at >= ? GROUP BY severity",
        (cutoff_7d,),
    ).fetchall()
    quality_map = {r[0]: r[1] for r in quality_counts}

    return {
        "all_ports_scraped_today": set(ports_succeeded) >= set(active_ports),
        "ports_succeeded": ports_succeeded,
        "ports_failed": ports_failed,
        "ports_not_attempted": sorted(set(active_ports) - set(ports_attempted)),
        "historical_gap_count": historical_gap_count,
        "coverage_holes": coverage_holes,
        "quality_issues_7d": {
            "errors": quality_map.get("error", 0),
            "warns": quality_map.get("warn", 0),
        },
    }


def _report_quality_issues(conn) -> list[dict]:
    """Return all quality_log issues from the last 7 days."""
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """SELECT checked_at, check_type, severity, port, date, species, grade, value, expected, message
           FROM quality_log WHERE checked_at >= ? ORDER BY checked_at DESC""",
        (cutoff,),
    ).fetchall()
    return [
        {
            "checked_at": r[0],
            "check_type": r[1],
            "severity": r[2],
            "port": r[3],
            "date": r[4],
            "species": r[5],
            "grade": r[6],
            "value": r[7],
            "expected": r[8],
            "message": r[9],
        }
        for r in rows
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = run_quality_checks()
    print(f"Quality check complete: {summary['errors']} errors, {summary['warns']} warnings")
    for issue in summary["issues"]:
        level = "ERROR" if issue["severity"] == "error" else "WARN "
        print(f"  [{level}] {issue['message']}")
