"""Extract prices from CSV files."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)


def extract_prices(file_path: Path, port: str, date: str) -> list[PriceRecord]:
    """Extract price records from a CSV file."""
    records = []
    now = datetime.now().isoformat()

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        # Sniff the dialect
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            logger.warning("CSV has no headers — falling back to AI extraction")
            from quayside.extractors.ai import extract_prices as ai_extract
            return ai_extract(file_path, port, date)

        # Map column names (case-insensitive)
        field_map = {}
        for field in reader.fieldnames:
            fl = field.lower().strip()
            if "species" in fl or "fish" in fl:
                field_map["species"] = field
            elif "grade" in fl:
                field_map["grade"] = field
            elif "low" in fl or "min" in fl:
                field_map["low"] = field
            elif "high" in fl or "max" in fl:
                field_map["high"] = field
            elif "avg" in fl or "average" in fl or "mean" in fl or "price" in fl and "avg" not in field_map:
                field_map["avg"] = field

        if "species" not in field_map:
            logger.warning("No species column found in CSV — falling back to AI extraction")
            from quayside.extractors.ai import extract_prices as ai_extract
            return ai_extract(file_path, port, date)

        for row in reader:
            species = row.get(field_map["species"], "").strip()
            if not species:
                continue

            grade = row.get(field_map.get("grade", ""), "").strip() if "grade" in field_map else ""
            low = _to_float(row.get(field_map.get("low", "")))
            high = _to_float(row.get(field_map.get("high", "")))
            avg = _to_float(row.get(field_map.get("avg", "")))

            if low is None and high is None and avg is None:
                continue
            if avg is None and low is not None and high is not None:
                avg = round((low + high) / 2, 2)

            records.append(PriceRecord(
                date=date, port=port, species=species, grade=grade,
                price_low=low, price_high=high, price_avg=avg, scraped_at=now,
            ))

    logger.info("Extracted %d prices from CSV for %s", len(records), port)
    return records


def _to_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    # Strip currency symbols
    cleaned = val.strip().lstrip("£$€").strip()
    try:
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return None
