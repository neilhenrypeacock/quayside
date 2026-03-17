"""Scrape Brixham fish prices from SWFPA daily PDF report.

The PDF (Daily-Fish-Sales-Report-N.pdf) is linked from the same SWFPA event
detail page as the Peterhead XLS. Use get_swfpa_event_links() in swfpa.py to
discover both URLs in a single HTTP round-trip.

PDF text format (one fish per line):
    SPECIES_NAME [GRADE_NUMBER] DEFRA_CODE  WEIGHT  DAY_AVG  WEEK_AVG

Examples:
    BL WING 1 RJH 94.10 7.90 7.92
    BREAM SBR 31.60 40.36 18.98
    TURBOT 2 TUR 27.00 44.29 41.89

DEFRA code (exactly 3 uppercase letters) is the reliable parsing anchor.
We store DAY_AVG as price_avg; price_low/high are None (PDF has no split).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from io import BytesIO

import pdfplumber
import requests

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)

PORT = "Brixham"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}

# Matches: SPECIES [GRADE] DEFRA_CODE WEIGHT DAY_AVG WEEK_AVG
# DEFRA code = exactly 3 uppercase letters (e.g. COD, RJH, TUR, SBR)
_ROW_RE = re.compile(r"^(.+?)\s+([A-Z]{3})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$")

# Lines to skip even if they match the row regex
_SKIP_KEYWORDS = {"DAILY TOTAL", "GRAND TOTAL", "WEEKLY TOTAL", "END OF REPORT"}


def scrape_prices(
    pdf_url: str | None = None,
    pdf_bytes: bytes | None = None,
    target_date: str | None = None,
) -> list[PriceRecord]:
    """Scrape Brixham prices from a SWFPA daily PDF report.

    Pass pdf_bytes for testing (skips HTTP fetch).
    Pass target_date as fallback if date cannot be extracted from the PDF.
    """
    if pdf_bytes is None:
        if pdf_url is None:
            logger.info("No Brixham PDF URL provided — skipping")
            return []
        try:
            resp = requests.get(pdf_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            pdf_bytes = resp.content
        except requests.RequestException as e:
            logger.warning("Could not fetch Brixham PDF: %s", e)
            return []

    lines = _extract_lines(pdf_bytes)
    date = _extract_date(lines) or target_date
    if not date:
        logger.warning("Could not determine date for Brixham PDF")
        return []

    scraped_at = datetime.utcnow().isoformat()
    records = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = _ROW_RE.match(line)
        if not m:
            continue

        species_grade_raw = m.group(1).strip()
        # group(2) = DEFRA code (not stored)
        weight_kg = float(m.group(3))
        day_avg = float(m.group(4))
        # group(5) = week avg (not stored)

        # Skip totals / footer lines
        if species_grade_raw.upper() in _SKIP_KEYWORDS:
            continue

        # Skip implausible prices — these are lot totals parsed as per-kg prices
        if day_avg > 500:
            logger.warning(
                "Skipping implausible Brixham price: %s = £%.2f/kg (likely a lot total)",
                species_grade_raw, day_avg,
            )
            continue

        # Parse species and optional grade number
        # e.g. "BL WING 1" → species="Bl Wing", grade="1"
        # e.g. "BREAM"     → species="Bream",   grade="ALL"
        parts = species_grade_raw.split()
        if len(parts) >= 2 and parts[-1].isdigit():
            species = " ".join(parts[:-1]).title()
            grade = parts[-1]
        else:
            species = species_grade_raw.title()
            grade = "ALL"

        records.append(
            PriceRecord(
                date=date,
                port=PORT,
                species=species,
                grade=grade,
                price_low=None,
                price_high=None,
                price_avg=round(day_avg, 2),
                weight_kg=round(weight_kg, 2) if weight_kg > 0 else None,
                scraped_at=scraped_at,
            )
        )

    logger.info("Scraped %d price records for %s on %s", len(records), PORT, date)
    return records


def _extract_lines(pdf_bytes: bytes) -> list[str]:
    """Extract all text lines from all pages of the PDF."""
    lines = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(text.splitlines())
    return lines


def _extract_date(lines: list[str]) -> str | None:
    """Look for a date in the first 30 lines of PDF text.

    Handles formats: DD/MM/YYYY, DD.MM.YYYY, 'DDth Month YYYY'.
    """
    for line in lines[:30]:
        # DD/MM/YYYY or DD.MM.YYYY
        m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", line)
        if m:
            try:
                dt = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # "13th March 2026" style
        m2 = re.search(r"(\d+)(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})", line)
        if m2:
            try:
                dt = datetime.strptime(f"{m2.group(1)} {m2.group(2)} {m2.group(3)}", "%d %B %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

    return None
