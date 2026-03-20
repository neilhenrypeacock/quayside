"""Data quality checks for Quayside.

Runs ten checks against the prices table and writes issues to quality_log.

Statistical checks (1–6):
  1. outlier_price   — per-record price >3.5× MAD from 30-day median (warn only)
  2. record_count    — today's count <40% of rolling median
  3. stale_data      — no new data for ≥2/4 trading days
  4. day_avg_spike   — port daily avg ±50%/100% from rolling avg
  5. seeded_data     — known seeded-data timestamp on live ports
  6. live_site       — displayed price on live site matches DB

Data-accuracy checks (7–11):
  7. unknown_field   — NULL/blank/Unknown in port or species fields
  8. unmapped_species — species with no canonical mapping; fuzzy-suggests fix
  9. price_sanity    — price ≤0, >£200/kg, or price_low > price_high
 10. date_sanity     — future-dated or pre-2020 records
 11. price_swing     — species >200%/500% vs 30-day mean (catches Gurnard-at-£50 style errors)

Designed to run after every successful scrape and 3× daily as backstop.

Usage:
    python -m quayside.quality
"""

from __future__ import annotations

import logging
import os
import re
import urllib.request
from datetime import date as date_type
from datetime import datetime, timedelta

from quayside.db import get_connection, init_db

_LIVE_SITE_URL = os.getenv("QUAYSIDE_SITE_URL", "https://quaysidedata.duckdns.org")
_SMOKE_TIMEOUT = 10  # seconds per port page fetch

logger = logging.getLogger(__name__)

# Active ports to monitor — excludes demo ports (data_method = 'demo')
_ACTIVE_PORTS_SQL = """
    SELECT name FROM ports WHERE status = 'active' AND data_method != 'demo'
"""

# Thresholds
_OUTLIER_MAD_THRESHOLD = 3.5  # robust z-score > 3.5× MAD from median → warn (no error)
_MIN_HISTORY_RECORDS = 10     # min records in 30-day history to run outlier check
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
    # record_count check removed — pipeline table already shows missing data clearly
    issues.extend(_check_stale_data(conn, date, checked_at, active_ports))
    issues.extend(_check_day_avg_spike(conn, date, checked_at, active_ports))
    issues.extend(_check_seeded_data(conn, date, checked_at, active_ports))
    issues.extend(_check_live_site(conn, date, checked_at, active_ports))
    issues.extend(_check_unknown_fields(conn, date, checked_at, active_ports))
    issues.extend(_check_unmapped_species(conn, date, checked_at, active_ports))
    issues.extend(_check_price_sanity(conn, date, checked_at, active_ports))
    issues.extend(_check_date_sanity(conn, date, checked_at, active_ports))
    issues.extend(_check_species_price_swing(conn, date, checked_at, active_ports))

    # Write all issues to quality_log — OR IGNORE skips duplicates (unique index on
    # check_type, severity, port, date, species, grade prevents the same issue being
    # logged multiple times per day even if the pipeline runs several times)
    conn.executemany(
        """INSERT OR IGNORE INTO quality_log
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
    """Flag prices that are statistical outliers vs. 30-day rolling history.

    Uses median + MAD (Median Absolute Deviation) instead of mean + σ so that
    missing trading days don't drag the baseline down and cause false positives.
    Emits warn only — no errors for price outliers.
    """
    from collections import defaultdict

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

        # Fetch all historical values per (species, grade) — needed for median/MAD
        history_rows = conn.execute(
            """SELECT species, grade, price_avg FROM prices
               WHERE port = ? AND date > ? AND date < ? AND price_avg IS NOT NULL""",
            (port, cutoff_30d, date),
        ).fetchall()

        # Group by (species, grade)
        history: dict[tuple, list[float]] = defaultdict(list)
        for species, grade, price_avg in history_rows:
            history[(species, grade)].append(price_avg)

        # Compute median + MAD for each key with enough data
        stats: dict[tuple, tuple] = {}
        for key, values in history.items():
            if len(values) < _MIN_HISTORY_RECORDS:
                continue
            med = _median(sorted(values))
            deviations = sorted(abs(v - med) for v in values)
            mad = _median(deviations)
            stats[key] = (med, mad)

        for species, grade, price_avg in today_rows:
            if (species, grade) not in stats:
                continue
            med, mad = stats[(species, grade)]
            if mad == 0:
                continue
            # Robust z-score: normalised by 1.4826*MAD (consistent with σ for normal distributions)
            robust_z = abs(price_avg - med) / (1.4826 * mad)
            if robust_z > _OUTLIER_MAD_THRESHOLD:
                issues.append(_issue(
                    checked_at, "outlier_price", "warn", port, date, species, grade,
                    value=round(price_avg, 2), expected=round(med, 2),
                    message=f"{species} {grade} at {port}: £{price_avg:.2f}/kg is {robust_z:.1f}× MAD from 30-day median (£{med:.2f}/kg)",
                ))

    return issues


# ── Check 2: Record count anomaly ────────────────────────────────────────────

def _check_record_count(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag if today's record count is unusually low vs. the port's rolling median."""
    issues = []
    is_today = date == date_type.today().isoformat()

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
            # SWFPA publishes auction results the day after — zero records for
            # the current date is expected until tomorrow's scrape fills them in.
            if is_today:
                continue
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


# ── Check 6: Live site smoke test ────────────────────────────────────────────

def _check_live_site(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Fetch each live port dashboard and verify the displayed avg price matches the DB.

    This is the only check that tests the display layer — all other checks
    only query the database. If the Flask route or Jinja template has a bug
    that causes the wrong price to render, this catches it.
    """
    issues = []

    # slug → port name from the ports table
    slug_rows = conn.execute(
        "SELECT slug, name FROM ports WHERE status='active' AND data_method != 'demo'"
    ).fetchall()
    slug_map = {r[0]: r[1] for r in slug_rows}

    # Compute DB avg price per port for today (same formula as Flask route)
    db_avgs: dict[str, float | None] = {}
    for port in active_ports:
        row = conn.execute(
            "SELECT AVG(price_avg) FROM prices WHERE port=? AND date=? AND price_avg IS NOT NULL",
            (port, date),
        ).fetchone()
        db_avgs[port] = round(row[0], 2) if row and row[0] is not None else None

    for slug, port_name in slug_map.items():
        if port_name not in active_ports:
            continue

        url = f"{_LIVE_SITE_URL}/port/{slug}"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Quayside-QualityCheck/1.0"}
            )
            with urllib.request.urlopen(req, timeout=_SMOKE_TIMEOUT) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Live site check: %s unreachable — %s", url, exc)
            issues.append(_issue(
                checked_at, "live_site", "warn", port_name, date,
                message=f"{port_name}: live page unreachable ({exc})",
            ))
            continue

        # Parse the hero avg price from the rendered HTML
        # Template: <div class="hero-value" id="hero-today-avg">&pound;X.XX</div>
        m = re.search(r'id="hero-today-avg"[^>]*>(.*?)</div>', html, re.DOTALL)
        db_avg = db_avgs.get(port_name)

        if not m:
            # Element only renders when today_data exists ({% if today_data %} block)
            if db_avg is not None:
                # DB has data but site isn't showing the hero strip — render bug
                issues.append(_issue(
                    checked_at, "live_site", "error", port_name, date,
                    expected=db_avg,
                    message=f"{port_name}: hero stats missing from live page but DB has £{db_avg:.2f}/kg avg — possible render error",
                ))
            else:
                logger.info("Live site OK: %s shows no-data card (DB has no data today)", port_name)
            continue

        content = m.group(1).strip()

        if "&pound;" in content:
            # Site is showing a price
            try:
                displayed = round(float(content.replace("&pound;", "").strip()), 2)
            except ValueError:
                issues.append(_issue(
                    checked_at, "live_site", "warn", port_name, date,
                    message=f"{port_name}: could not parse displayed price '{content}'",
                ))
                continue

            if db_avg is None:
                # Site is showing a carry-forward price from a previous date — expected when
                # today's data hasn't landed yet. record_count errors already cover this case.
                logger.info(
                    "Live site: %s shows £%.2f/kg but no DB data for today — historical carry-forward",
                    port_name, displayed,
                )
            elif abs(displayed - db_avg) > 0.02:
                # Divergence > 2p — mismatch between DB and rendered page
                issues.append(_issue(
                    checked_at, "live_site", "error", port_name, date,
                    value=displayed, expected=db_avg,
                    message=(
                        f"{port_name}: live site shows £{displayed:.2f}/kg "
                        f"but DB avg is £{db_avg:.2f}/kg — display layer mismatch"
                    ),
                ))
            else:
                logger.info("Live site OK: %s shows £%.2f/kg (DB: £%.2f/kg)", port_name, displayed, db_avg)
        else:
            # Site is showing "—" (no data)
            if db_avg is not None:
                issues.append(_issue(
                    checked_at, "live_site", "error", port_name, date,
                    expected=db_avg,
                    message=(
                        f"{port_name}: live site shows '—' but DB avg is £{db_avg:.2f}/kg "
                        f"— data exists but not rendering"
                    ),
                ))
            else:
                logger.info("Live site OK: %s shows '—', DB has no data for today", port_name)

    return issues


# ── Check 7: Unknown / blank field values ────────────────────────────────────

def _check_unknown_fields(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag records with NULL, blank, or 'Unknown' in species or all price fields.

    Covers the last 14 days so bad records from recent scrapes are caught even
    if the pipeline ran on a different date than today's check.
    Also checks for records where the port field itself is null/unknown.
    """
    issues = []
    cutoff = (datetime.fromisoformat(date) - timedelta(days=14)).date().isoformat()

    for port in active_ports:
        # Species is NULL or blank
        rows = conn.execute(
            """SELECT date, COUNT(*) FROM prices
               WHERE port = ? AND date >= ? AND date <= ?
               AND (species IS NULL OR TRIM(species) = '')
               GROUP BY date""",
            (port, cutoff, date),
        ).fetchall()
        for row_date, count in rows:
            issues.append(_issue(
                checked_at, "unknown_field", "error", port, row_date,
                message=f"{port} {row_date}: {count} record(s) with NULL or blank species",
            ))

        # Species contains "unknown" (case-insensitive)
        rows = conn.execute(
            """SELECT date, species, COUNT(*) FROM prices
               WHERE port = ? AND date >= ? AND date <= ?
               AND LOWER(species) LIKE '%unknown%'
               GROUP BY date, species""",
            (port, cutoff, date),
        ).fetchall()
        for row_date, species, count in rows:
            issues.append(_issue(
                checked_at, "unknown_field", "error", port, row_date,
                species=species,
                message=f"{port} {row_date}: species is '{species}' ({count} record(s)) — port name did not resolve",
            ))

        # All price fields NULL (no usable price data)
        rows = conn.execute(
            """SELECT date, COUNT(*) FROM prices
               WHERE port = ? AND date >= ? AND date <= ?
               AND price_avg IS NULL AND price_low IS NULL AND price_high IS NULL
               GROUP BY date""",
            (port, cutoff, date),
        ).fetchall()
        for row_date, count in rows:
            issues.append(_issue(
                checked_at, "unknown_field", "warn", port, row_date,
                message=f"{port} {row_date}: {count} record(s) with all price fields NULL",
            ))

    # Catch records where the port column itself is null/blank/unknown (any port, any date)
    bad_port_rows = conn.execute(
        """SELECT port, date, COUNT(*) FROM prices
           WHERE date >= ? AND date <= ?
           AND (port IS NULL OR TRIM(port) = '' OR LOWER(port) LIKE '%unknown%')
           GROUP BY port, date""",
        (cutoff, date),
    ).fetchall()
    for bad_port, row_date, count in bad_port_rows:
        issues.append(_issue(
            checked_at, "unknown_field", "error", bad_port or "(blank)", row_date,
            message=f"Port field is '{bad_port or '(blank)'}' on {row_date} ({count} record(s)) — scraper returned wrong port name",
        ))

    return issues


# ── Check 8: Unmapped species names (with fuzzy suggestions) ─────────────────

def _check_unmapped_species(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag species names with no canonical mapping. Uses fuzzy matching to
    suggest the most likely canonical name so the fix is obvious:
      - ratio ≥ 0.75 → "likely 'Monkfish' — add to _CANONICAL_MAP"
      - ratio 0.5–0.74 → "possible match 'Monkfish' — review needed"
      - no match  → "no close match — new species or typo"
    """
    import difflib

    from quayside.species import _RAW_TO_CANONICAL, is_noisy_species

    # All known raw names (lowercased) for fuzzy matching
    all_known_raw = list(_RAW_TO_CANONICAL.keys())

    issues = []

    for port in active_ports:
        species_rows = conn.execute(
            "SELECT DISTINCT species FROM prices WHERE port = ? AND date = ? AND species IS NOT NULL",
            (port, date),
        ).fetchall()

        for (raw_species,) in species_rows:
            if not raw_species or not raw_species.strip():
                continue
            if is_noisy_species(raw_species):
                continue  # intentionally filtered — not a mapping problem
            if raw_species.lower() in _RAW_TO_CANONICAL:
                continue  # already mapped

            # Fuzzy match against all known raw names
            close = difflib.get_close_matches(raw_species.lower(), all_known_raw, n=1, cutoff=0.5)
            if close:
                best_raw = close[0]
                canonical = _RAW_TO_CANONICAL[best_raw]
                ratio = difflib.SequenceMatcher(None, raw_species.lower(), best_raw).ratio()
                if ratio >= 0.75:
                    action = f"likely '{canonical}' — add \"{raw_species}\": \"{canonical}\" to _CANONICAL_MAP in species.py"
                else:
                    action = f"possible match '{canonical}' — review before adding to species.py"
            else:
                action = "no close match found — new species or typo, check source data"

            issues.append(_issue(
                checked_at, "unmapped_species", "warn", port, date,
                species=raw_species,
                message=f"'{raw_species}' at {port}: unmapped species — {action}",
            ))

    return issues


# ── Check 9: Price sanity ─────────────────────────────────────────────────────

_MAX_PLAUSIBLE_PRICE = 200.0   # £/kg — above this, likely a lot-total leak
_MIN_PLAUSIBLE_PRICE = 0.0     # £/kg — at or below this is impossible


def _check_price_sanity(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag prices that are impossible or suspiciously extreme."""
    issues = []

    for port in active_ports:
        # price_avg <= 0 → impossible → error
        rows = conn.execute(
            """SELECT species, grade, price_avg FROM prices
               WHERE port = ? AND date = ? AND price_avg IS NOT NULL AND price_avg <= 0""",
            (port, date),
        ).fetchall()
        for species, grade, price_avg in rows:
            issues.append(_issue(
                checked_at, "price_sanity", "error", port, date, species, grade,
                value=round(price_avg, 4),
                message=f"{species or '?'} {grade or ''} at {port}: price_avg £{price_avg:.2f}/kg is ≤0 — impossible value",
            ))

        # price_avg > £200/kg → likely lot-total misread as per-kg price → warn
        rows = conn.execute(
            """SELECT species, grade, price_avg FROM prices
               WHERE port = ? AND date = ? AND price_avg > ?""",
            (port, date, _MAX_PLAUSIBLE_PRICE),
        ).fetchall()
        for species, grade, price_avg in rows:
            issues.append(_issue(
                checked_at, "price_sanity", "warn", port, date, species, grade,
                value=round(price_avg, 2),
                message=f"{species or '?'} {grade or ''} at {port}: price_avg £{price_avg:.2f}/kg exceeds £{_MAX_PLAUSIBLE_PRICE:.0f}/kg — possible lot-total leak",
            ))

        # price_low > price_high → inverted range → error
        rows = conn.execute(
            """SELECT species, grade, price_low, price_high FROM prices
               WHERE port = ? AND date = ?
               AND price_low IS NOT NULL AND price_high IS NOT NULL
               AND price_low > price_high""",
            (port, date),
        ).fetchall()
        for species, grade, price_low, price_high in rows:
            issues.append(_issue(
                checked_at, "price_sanity", "error", port, date, species, grade,
                value=round(price_low, 2), expected=round(price_high, 2),
                message=f"{species or '?'} {grade or ''} at {port}: price_low £{price_low:.2f} > price_high £{price_high:.2f} — inverted range",
            ))

    return issues


# ── Check 10: Date sanity ─────────────────────────────────────────────────────

_OLDEST_PLAUSIBLE_DATE = "2020-01-01"


def _check_date_sanity(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag records with future or implausibly old dates."""
    issues = []

    # Future-dated records (could be timezone or scraper clock issue)
    future_rows = conn.execute(
        """SELECT port, date, COUNT(*) FROM prices
           WHERE date > ? GROUP BY port, date""",
        (date,),
    ).fetchall()
    for port, bad_date, count in future_rows:
        issues.append(_issue(
            checked_at, "date_sanity", "error", port, bad_date,
            message=f"{port}: {count} record(s) dated {bad_date} — future date, check scraper timezone",
        ))

    # Pre-2020 records (likely seeded or test data that crept in)
    old_rows = conn.execute(
        """SELECT port, date, COUNT(*) FROM prices
           WHERE date < ? GROUP BY port, date""",
        (_OLDEST_PLAUSIBLE_DATE,),
    ).fetchall()
    for port, bad_date, count in old_rows:
        issues.append(_issue(
            checked_at, "date_sanity", "warn", port, bad_date,
            message=f"{port}: {count} record(s) dated {bad_date} — before 2020, likely seeded or test data",
        ))

    return issues


# ── Check 11: Per-species price swing ────────────────────────────────────────

_SWING_ERROR_PCT = 500.0   # >500% change vs 30-day mean → error
_SWING_WARN_PCT  = 200.0   # >200% change vs 30-day mean → warn


def _check_species_price_swing(conn, date: str, checked_at: str, active_ports: list[str]) -> list[dict]:
    """Flag individual species/grade combinations where today's price deviates
    wildly from the 30-day mean for that species at that port.

    Unlike _check_outlier_prices (which needs ≥10 history records and uses σ),
    this check uses a simple percentage and fires with just 1 historical record —
    catching rare species that only trade occasionally.

    Example: Gurnard at £50/kg when the 30-day mean is £1/kg = 5000% → error.
    """
    issues = []
    cutoff_30d = (datetime.fromisoformat(date) - timedelta(days=30)).date().isoformat()

    for port in active_ports:
        today_rows = conn.execute(
            """SELECT species, grade, price_avg FROM prices
               WHERE port = ? AND date = ? AND price_avg IS NOT NULL AND price_avg > 0""",
            (port, date),
        ).fetchall()

        for species, grade, today_price in today_rows:
            row = conn.execute(
                """SELECT AVG(price_avg) FROM prices
                   WHERE port = ? AND species = ? AND grade = ?
                   AND date > ? AND date < ?
                   AND price_avg IS NOT NULL AND price_avg > 0""",
                (port, species, grade, cutoff_30d, date),
            ).fetchone()
            hist_avg = row[0] if row else None

            if hist_avg is None or hist_avg == 0:
                continue  # no history — can't compare

            pct_change = abs(today_price - hist_avg) / hist_avg * 100

            if pct_change >= _SWING_ERROR_PCT:
                severity = "error"
            elif pct_change >= _SWING_WARN_PCT:
                severity = "warn"
            else:
                continue

            direction = "above" if today_price > hist_avg else "below"
            issues.append(_issue(
                checked_at, "price_swing", severity, port, date, species, grade,
                value=round(today_price, 2), expected=round(hist_avg, 2),
                message=(
                    f"{species} {grade or ''} at {port}: £{today_price:.2f}/kg is "
                    f"{pct_change:.0f}% {direction} 30-day mean (£{hist_avg:.2f}/kg) "
                    f"— likely a scraper error"
                ).strip(),
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
    from quayside.db import get_market_averages_for_date, get_same_day_last_week
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
        canonical_species = {normalise_species(r[0]) for r in rows} - {None}
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
        no_benchmark_set = set()
        for r in rows:
            canon = normalise_species(r[0])
            if canon is None:
                continue
            if market.get(canon, {}).get("port_count", 0) < 2:
                no_benchmark_set.add(canon)
        no_benchmark = sorted(no_benchmark_set)

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
        from quayside.report import BENCHMARK_SPECIES, build_report_data
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
           WHERE date >= ? AND date <= ?
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
           WHERE date >= date(?, '-14 days') AND date < ?""",
        (date, date),
    ).fetchone()[0]
    # Rough: 10 weekdays in 2 weeks, minus days with data
    historical_gap_count = max(0, 10 - gap_count)

    # Quality issues summary — deduplicated so repeated pipeline runs don't inflate counts
    cutoff_7d = (datetime.utcnow() - timedelta(days=7)).isoformat()
    quality_counts = conn.execute(
        """SELECT severity, COUNT(*) FROM (
               SELECT DISTINCT check_type, severity, port, date, species, grade
               FROM quality_log WHERE checked_at >= ?
           ) GROUP BY severity""",
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
    """Return deduplicated quality_log issues from the last 7 days."""
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """SELECT MAX(checked_at), check_type, severity, port, date, species, grade, value, expected, message
           FROM quality_log WHERE checked_at >= ?
           GROUP BY check_type, severity, port, date, species, grade, value, expected, message
           ORDER BY date DESC, severity, port""",
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

    # Step 1: statistical checks → writes issues to quality_log
    summary = run_quality_checks()
    print(f"Quality check complete: {summary['errors']} errors, {summary['warns']} warnings")
    for issue in summary["issues"]:
        level = "ERROR" if issue["severity"] == "error" else "WARN "
        print(f"  [{level}] {issue['message']}")

    # Step 2: comprehensive report — port dashboards, digest preview, ops health
    print("\n--- Comprehensive Report ---")
    report = build_comprehensive_report()

    # Port dashboards
    print(f"\nPort Dashboards ({report['date']}):")
    for p in report["port_dashboards"]:
        status = "OK" if p["has_today_data"] else "NO DATA"
        avg = f"£{p['today_avg']:.2f}/kg" if p["today_avg"] else "—"
        vs_lw = (f"{p['vs_last_week_pct']:+.1f}% vs last week" if p["vs_last_week_pct"] is not None else "— vs last week")
        vs_mkt = (f"{p['vs_market_pct']:+.1f}% vs market" if p["vs_market_pct"] is not None else "— vs market")
        print(f"  [{status}] {p['port']}: {p['record_count']} records, avg {avg}, {vs_lw}, {vs_mkt}")
        if p["hero_nulls"] and not p["hero_null_expected"]:
            print(f"    WARNING: unexpected null hero stats: {', '.join(p['hero_nulls'])}")

    # Digest preview
    dp = report["digest_preview"]
    if dp.get("error"):
        print(f"\nDigest preview: ERROR — {dp['error']}")
    else:
        print(f"\nDigest preview: {len(dp['ports_reporting'])} ports reporting, "
              f"{dp['total_species']} species, "
              f"{dp['benchmark_species_available']}/10 benchmark species, "
              f"{dp['movers_count']} movers")
        if dp["missing_from_digest"]:
            print(f"  Missing from digest: {', '.join(dp['missing_from_digest'])}")
        if dp["benchmark_species_missing"]:
            print(f"  Benchmark species missing: {', '.join(dp['benchmark_species_missing'])}")

    # Ops health
    oh = report["ops_health"]
    print(f"\nOps health: {len(oh['ports_succeeded'])}/{len(oh['ports_succeeded']) + len(oh['ports_failed']) + len(oh['ports_not_attempted'])} ports scraped today")
    if oh["ports_failed"]:
        print(f"  Failed: {', '.join(oh['ports_failed'])}")
    if oh["ports_not_attempted"]:
        print(f"  Not attempted: {', '.join(oh['ports_not_attempted'])}")
    if oh["coverage_holes"]:
        for hole in oh["coverage_holes"]:
            print(f"  Coverage hole: {hole['port']} — only {hole['days_in_recent']} days in recent window")
