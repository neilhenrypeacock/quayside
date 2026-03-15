"""Extract prices from PDF files using pdfplumber.

For unknown layouts, falls back to AI extraction of the extracted text.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)


def extract_prices(file_path: Path, port: str, date: str) -> list[PriceRecord]:
    """Extract price records from a PDF file."""
    import pdfplumber

    records = []
    now = datetime.now().isoformat()

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Detect header row
                headers = {}
                header_cells = [str(c).lower().strip() if c else "" for c in table[0]]
                for i, cell in enumerate(header_cells):
                    if "species" in cell or "fish" in cell:
                        headers["species"] = i
                    elif "grade" in cell:
                        headers["grade"] = i
                    elif "low" in cell or "min" in cell:
                        headers["low"] = i
                    elif "high" in cell or "max" in cell:
                        headers["high"] = i
                    elif "avg" in cell or "average" in cell or "mean" in cell or "price" in cell and "avg" not in headers:
                        headers["avg"] = i

                if "species" not in headers:
                    continue

                for row in table[1:]:
                    if not row or len(row) <= max(headers.values()):
                        continue

                    species = str(row[headers["species"]] or "").strip()
                    if not species:
                        continue

                    grade = ""
                    if "grade" in headers and row[headers["grade"]]:
                        grade = str(row[headers["grade"]]).strip()

                    low = _to_float(row[headers["low"]]) if "low" in headers else None
                    high = _to_float(row[headers["high"]]) if "high" in headers else None
                    avg = _to_float(row[headers["avg"]]) if "avg" in headers else None

                    if low is None and high is None and avg is None:
                        continue
                    if avg is None and low is not None and high is not None:
                        avg = round((low + high) / 2, 2)

                    records.append(PriceRecord(
                        date=date, port=port, species=species, grade=grade,
                        price_low=low, price_high=high, price_avg=avg, scraped_at=now,
                    ))

    if records:
        logger.info("Extracted %d prices from PDF for %s", len(records), port)
        return records

    # Fallback: extract all text and use AI
    logger.info("No tables found in PDF — falling back to AI extraction")
    from quayside.extractors.ai import extract_prices as ai_extract
    return ai_extract(file_path, port, date)


def _to_float(val) -> float | None:
    if val is None:
        return None
    cleaned = str(val).strip().lstrip("£$€").strip()
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return None
