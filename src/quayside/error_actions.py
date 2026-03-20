"""Error dashboard fix actions, plain-English explanations, and markdown export.

Maps quality check_type values to fix actions and human-readable descriptions.
Used by ops_views.py error dashboard routes.
"""

from __future__ import annotations

from datetime import datetime

from quayside.db import get_connection

# ── Fix action types per check_type ─────────────────────────────────────────
# Keys match the check_type strings from quality.py exactly.

FIX_ACTIONS = {
    "outlier_price":    "flag_record",
    "price_sanity":     "flag_record",
    "price_swing":      "flag_record",
    "day_avg_spike":    "flag_port_day",
    "record_count":     "mark_thin",
    "unknown_field":    "flag_record",
    "date_sanity":      "flag_record",
    "stale_data":       "download_only",
    "seeded_data":      "download_only",
    "live_site":        "download_only",
    "unmapped_species": "download_only",
}


# ── Fix functions ───────────────────────────────────────────────────────────


def _ensure_flagged_column(conn) -> None:
    """Add flagged column to prices table if it doesn't exist."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(prices)").fetchall()}
    if "flagged" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN flagged INTEGER DEFAULT 0")


def apply_flag_record(error: dict) -> str:
    """Flag a specific price record matching date, port, species."""
    conn = get_connection()
    _ensure_flagged_column(conn)

    # Extract date from the detail string (format: "... · Date: YYYY-MM-DD")
    date_val = _extract_date(error.get("detail", ""))
    port = error.get("port")
    species = error.get("species")

    if date_val and port and species:
        conn.execute(
            "UPDATE prices SET flagged = 1 WHERE date = ? AND port = ? AND species = ?",
            (date_val, port, species),
        )
    elif date_val and port:
        conn.execute(
            "UPDATE prices SET flagged = 1 WHERE date = ? AND port = ?",
            (date_val, port),
        )

    conn.commit()
    conn.close()
    return "Record flagged and excluded from averages"


def apply_flag_port_day(error: dict) -> str:
    """Flag all records for a port on a given day."""
    conn = get_connection()
    _ensure_flagged_column(conn)

    date_val = _extract_date(error.get("detail", ""))
    port = error.get("port")

    if date_val and port:
        conn.execute(
            "UPDATE prices SET flagged = 1 WHERE date = ? AND port = ?",
            (date_val, port),
        )

    conn.commit()
    conn.close()
    return "Port data for this day marked as anomalous"


def apply_mark_thin(error: dict) -> str:
    """Flag all records for a port on a given day as thin data."""
    conn = get_connection()
    _ensure_flagged_column(conn)

    date_val = _extract_date(error.get("detail", ""))
    port = error.get("port")

    if date_val and port:
        conn.execute(
            "UPDATE prices SET flagged = 1 WHERE date = ? AND port = ?",
            (date_val, port),
        )

    conn.commit()
    conn.close()
    return "Port data marked as thin for this date"


def apply_fix(error: dict) -> str:
    """Router: look up the fix action for this error and apply it."""
    action = FIX_ACTIONS.get(error.get("check_name", ""))
    if action == "download_only":
        raise ValueError("This error requires manual investigation — export to review.")
    if action == "flag_record":
        return apply_flag_record(error)
    if action == "flag_port_day":
        return apply_flag_port_day(error)
    if action == "mark_thin":
        return apply_mark_thin(error)
    raise ValueError(f"Unknown fix action: {action}")


def _extract_date(detail: str) -> str | None:
    """Extract a YYYY-MM-DD date from the detail string."""
    if not detail:
        return None
    # Look for "Date: YYYY-MM-DD" pattern
    for part in detail.split(" · "):
        if part.startswith("Date: ") and len(part) >= 16:
            return part[6:16]
    return None


# ── Plain English explanations ──────────────────────────────────────────────
# Keys match the check_type strings from quality.py exactly.

PLAIN_ENGLISH = {
    "outlier_price": (
        "A price in today's data is unusually far outside the normal range for "
        "this species. It's probably a data entry error or a scraping glitch — "
        "not a real market price. Fixing this flags the record so it is excluded "
        "from averages and charts."
    ),
    "price_sanity": (
        "A price record has a value that makes no sense — either zero, negative, "
        "over \u00a3200/kg, or where the low price is higher than the high price. "
        "This is always a data error. Fixing this flags the record."
    ),
    "price_swing": (
        "A price has jumped or dropped dramatically compared to its 30-day average — "
        "more than double or half what is normal. Could be real (a short supply event) "
        "or a scraping error. Worth checking before fixing."
    ),
    "day_avg_spike": (
        "The overall average price across all species at this port today is "
        "significantly higher or lower than usual. This could mean the scraper "
        "picked up bad data for multiple species, or that today was genuinely "
        "unusual at auction. Fixing marks this port and day as anomalous."
    ),
    "record_count": (
        "We got far fewer price records from this port than usual today — less "
        "than 40% of the normal amount. The scraper may have partially failed, "
        "or the port published an incomplete file. Fixing marks today's data "
        "as thin so the dashboard shows a warning."
    ),
    "unknown_field": (
        "Some records have missing or unknown values in fields that should "
        "always have data. This usually means the scraper could not parse part "
        "of the source file. Fixing flags these records for review."
    ),
    "date_sanity": (
        "A record has a date that is either in the future or more than a year "
        "old. This is always a parsing error. Fixing flags the record."
    ),
    "stale_data": (
        "We have not received any new data from this port for 2 or more trading "
        "days. The port may have stopped publishing, the scraper may be broken, "
        "or their file format may have changed. This needs a human to investigate — "
        "export this error to review in Claude chat."
    ),
    "seeded_data": (
        "A live port has data that appears to have been seeded during testing. "
        "This means test data may have leaked into production. Needs manual "
        "investigation — export to review."
    ),
    "live_site": (
        "The automated check that visits the live website found a price on the "
        "dashboard that does not match what is in the database. The site may be "
        "showing stale or cached data. Needs a human to look at — export to review."
    ),
    "unmapped_species": (
        "A species name has appeared in the data that we do not have a mapping "
        "for. It will not appear correctly in the dashboard or digest. You will "
        "need to add it to the species map manually — export to review."
    ),
}


# ── Human-readable check name labels ────────────────────────────────────────

_CHECK_LABELS = {
    "outlier_price": "Outlier Price",
    "price_sanity": "Price Sanity",
    "price_swing": "Price Swing",
    "day_avg_spike": "Daily Average Spike",
    "record_count": "Low Record Count",
    "unknown_field": "Unknown Fields",
    "date_sanity": "Date Sanity",
    "stale_data": "Stale Data",
    "seeded_data": "Seeded Data",
    "live_site": "Live Site Mismatch",
    "unmapped_species": "Unmapped Species",
}


# ── Markdown export ─────────────────────────────────────────────────────────


def generate_error_markdown(errors: list[dict], date_str: str) -> str:
    """Generate a markdown error report from error_log entries."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    open_errors = [e for e in errors if e["status"] == "open"]
    resolved_errors = [e for e in errors if e["status"] == "resolved"]

    open_err_count = sum(1 for e in open_errors if e["severity"] == "error")
    open_warn_count = sum(1 for e in open_errors if e["severity"] == "warning")

    lines = [
        "# Quayside Error Report",
        f"Generated: {now_str}",
        "",
    ]

    # Open errors section
    if open_errors:
        lines.append(f"## Open Errors — {open_err_count} errors, {open_warn_count} warnings")
        lines.append("")

        for e in open_errors:
            sev = e["severity"].upper()
            label = _CHECK_LABELS.get(e["check_name"], e["check_name"])
            port_str = f" · {e['port']}" if e.get("port") else ""
            lines.append(f"### {sev} — {label}{port_str}")

            if e.get("species"):
                lines.append(f"**Species:** {e['species']}")

            check_name = e.get("check_name", "")
            explanation = PLAIN_ENGLISH.get(check_name)
            if explanation:
                lines.append(f"**What this means:** {explanation}")

            if e.get("detail"):
                # Show detail but strip the "Date:" suffix for cleaner display
                detail = e["detail"]
                lines.append(f"**Detail:** {detail}")

            if e.get("scanned_at"):
                lines.append(f"**Logged:** {e['scanned_at'][:16].replace('T', ' ')} UTC")

            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("## No Open Errors")
        lines.append("")

    # Resolved section
    if resolved_errors:
        lines.append(f"## Resolved in last 48 hours — {len(resolved_errors)}")
        lines.append("")

        for e in resolved_errors:
            label = _CHECK_LABELS.get(e["check_name"], e["check_name"])
            port_str = f" · {e['port']}" if e.get("port") else ""
            lines.append(f"### RESOLVED — {label}{port_str}")

            if e.get("resolution"):
                lines.append(f"**Resolution:** {e['resolution']}")
            if e.get("resolved_at"):
                lines.append(f"**Resolved:** {e['resolved_at'][:16].replace('T', ' ')} UTC")

            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append(
        "*Export from Quayside ops dashboard. "
        "Paste into Claude chat to investigate download_only errors.*"
    )

    return "\n".join(lines)
