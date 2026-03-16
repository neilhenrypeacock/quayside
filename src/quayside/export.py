"""Export data from SQLite to CSV files."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from quayside.db import get_prices_by_date

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def export_prices_csv(date: str, port: str) -> Path | None:
    rows = get_prices_by_date(date, port)
    if not rows:
        logger.warning("No price data to export for %s %s", port, date)
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"prices_{port.lower()}_{date}.csv"

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["date", "port", "species", "grade", "price_low", "price_high", "price_avg"]
        )
        writer.writerows(rows)

    logger.info("Exported %d price rows to %s", len(rows), path)
    return path
