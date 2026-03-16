"""Backfill the last N trading days of Peterhead prices from SWFPA.

Usage:
    cd /path/to/quayside
    python scripts/backfill_peterhead.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

from quayside.scrapers.swfpa import get_swfpa_event_links, scrape_prices
from quayside.db import upsert_prices

TRADING_DAYS_TARGET = 25  # aim for 25 to guarantee 20 complete days


def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def backfill() -> None:
    today = datetime.now()
    fetched = 0
    day_offset = 0
    seen_event_dates: set[str] = set()

    print(f"Backfilling last {TRADING_DAYS_TARGET} trading days of Peterhead prices...")

    while fetched < TRADING_DAYS_TARGET and day_offset < 90:
        candidate = today - timedelta(days=day_offset)
        day_offset += 1
        if not _is_weekday(candidate):
            continue

        date_str = candidate.strftime("%Y-%m-%d")
        links = get_swfpa_event_links(target_date=date_str)
        if not links or not links.get("peterhead_xls"):
            print(f"  {date_str}: no XLS link found — skipping")
            continue

        event_date = links.get("event_date", date_str)

        if event_date in seen_event_dates:
            # Same event as a previous day — count it but don't re-download
            print(f"  {date_str}: maps to event {event_date} (already fetched) — counting")
            fetched += 1
            continue

        seen_event_dates.add(event_date)
        records = scrape_prices(xls_url=links["peterhead_xls"])
        if records:
            upsert_prices(records)
            print(f"  ✓ {event_date}: {len(records)} records upserted")
            fetched += 1
        else:
            print(f"  {date_str}: XLS returned no records")

    print(f"\nDone. Fetched data for {fetched} trading day(s).")


if __name__ == "__main__":
    backfill()
