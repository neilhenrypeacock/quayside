"""Scrape Newlyn fish prices from SWFPA daily PDF report.

The PDF is linked from the same SWFPA event detail page as the Peterhead XLS
and Brixham PDF. Named by date (e.g. "9TH.pdf", "6th.pdf").

PDF text format (one fish per line):
    SPECIES (GRADE) SIZE_DESC WEIGHT AVERAGE

Examples:
    Dover Sole (1) 801g+ 556.3 16.2
    Cuttlefish (1) 0.5Kg+ 875.2 4.0
    Megrim (3) 0.5-0.7Kg 257.1 6.6
    Flounder/Fluke 9 13.5 1.0

Weight is in kg, Average is £/kg. We store avg as price_avg.
Some species have no grade (e.g. "Flounder/Fluke 9 13.5 1.0").
The "Grand Total" row is skipped.
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

PORT = "Newlyn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}

# Match lines like: SPECIES (GRADE) SIZE WEIGHT AVG
# or: SPECIES SIZE WEIGHT AVG (no grade)
# or: SPECIES - WEIGHT AVG (dash as size placeholder)
_ROW_RE = re.compile(r"^(.+?)\s+([\d,.]+)\s+([\d,.]+)\s*$")

_SKIP = {"grand total", "newlyn market"}


def scrape_prices(
    pdf_url: str | None = None,
    pdf_bytes: bytes | None = None,
    target_date: str | None = None,
) -> list[PriceRecord]:
    """Scrape Newlyn prices from a SWFPA daily PDF report."""
    if pdf_bytes is None:
        if pdf_url is None:
            logger.info("No Newlyn PDF URL provided — skipping")
            return []
        try:
            resp = requests.get(pdf_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            pdf_bytes = resp.content
        except requests.RequestException as e:
            logger.warning("Could not fetch Newlyn PDF: %s", e)
            return []

    lines = _extract_lines(pdf_bytes)
    date = _extract_date(lines) or target_date
    if not date:
        logger.warning("Could not determine date for Newlyn PDF")
        return []

    scraped_at = datetime.utcnow().isoformat()
    records = []
    current_species = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip header/total lines
        if any(skip in line.lower() for skip in _SKIP):
            continue
        if line.lower().startswith("species"):
            continue

        m = _ROW_RE.match(line)
        if not m:
            continue

        prefix = m.group(1).strip()
        weight_str = m.group(2).replace(",", "")
        avg_str = m.group(3).replace(",", "")

        try:
            avg = float(avg_str)
            weight_kg = float(weight_str) if weight_str else None
        except ValueError:
            continue

        # Skip zero-price rows
        if avg <= 0:
            continue

        # Parse species and grade from prefix
        # Examples:
        #   "Dover Sole (1) 801g+"              → species="Dover Sole", grade="1"
        #   "Mackerel (LM) 0.33-0.45Kg"         → species="Mackerel", grade="LM"
        #   "(S) 0-0.2Kg"                        → species=current_species, grade="S"
        #   "Flounder/Fluke 9"                   → species="Flounder/Fluke", grade="ALL"
        #   "Wings - Blonde (2) 1-1.5Kg"         → species="Wings - Blonde", grade="2"
        #   "Megrim (2) Damaged (2) Damaged"      → species="Megrim Damaged", grade="2"
        #   "(6) Damaged"                         → species=current_species + " Damaged", grade="6"
        #   "Weaver -"                            → species="Weaver", grade="ALL"

        # Check for continuation lines starting with (grade)
        size_band: str | None = None
        cont_match = re.match(r"^\(([^)]+)\)\s*(.*)", prefix)
        if cont_match:
            grade = cont_match.group(1)
            after = cont_match.group(2).strip()
            if current_species:
                species_part = current_species
                if "damaged" in after.lower():
                    species_part = f"{current_species} Damaged"
                elif after:
                    size_band = after
            else:
                continue
        else:
            grade_match = re.search(r"\(([^)]+)\)", prefix)
            if grade_match:
                grade = grade_match.group(1)
                species_part = prefix[: grade_match.start()].strip()
                after_grade = prefix[grade_match.end() :].strip()
                if "damaged" in after_grade.lower():
                    species_part = f"{species_part} Damaged"
                elif after_grade:
                    size_band = after_grade
            else:
                grade = "ALL"
                # Remove size/trailing descriptors
                parts = prefix.split()
                species_parts = []
                for p in parts:
                    if re.match(r"^\d", p) or p.lower() in ("mixed",):
                        break
                    species_parts.append(p)
                species_part = " ".join(species_parts) if species_parts else prefix

        species = species_part.strip().rstrip(" -")
        if not species:
            continue

        # Track current species for continuation lines
        if not cont_match and "damaged" not in species.lower():
            current_species = species

        records.append(
            PriceRecord(
                date=date,
                port=PORT,
                species=species,
                grade=grade,
                price_low=None,
                price_high=None,
                price_avg=round(avg, 2),
                weight_kg=round(weight_kg, 2) if weight_kg and weight_kg > 0 else None,
                scraped_at=scraped_at,
                size_band=size_band,
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
    """Look for a date in the first few lines.

    Header format: "Newlyn Market 9th March 2026"
    """
    for line in lines[:5]:
        m = re.search(r"(\d+)(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})", line)
        if m:
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None
