"""Scrape Lerwick fish landings from shetlandauction.com."""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from quayside.models import LandingRecord

logger = logging.getLogger(__name__)

URL = "https://www.shetlandauction.com/ssa-today"
PORT = "Lerwick"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}

# Column indices (0-based, after removing vessel/method/total/shots cols)
# Data cells per vessel row: indices 0-38
# 0: vessel, 1: catch method, 2: total, 3: shots to come
# 4-10: HADDOCK grades 1,2,3,4,5,6,Rnd
# 11-14: WHITING grades 2,3,4,Rnd
# 15-18: COD grades 1,2,3,4
# 19-22: SAITHE grades 2,3,4,5
# 23-38: single-species columns
GRADED_SPECIES = {
    "Haddock": (4, 11),  # cols 4-10 inclusive
    "Whiting": (11, 15),  # cols 11-14
    "Cod": (15, 19),  # cols 15-18
    "Saithe": (19, 23),  # cols 19-22
}
SINGLE_SPECIES = [
    (23, "Plaice"),
    (24, "Megrim"),
    (25, "Monks"),
    (26, "Ling"),
    (27, "Skate"),
    (28, "Lemon Sole"),
    (29, "Lythe"),
    (30, "Squid"),
    (31, "Witches"),
    (32, "Catfish"),
    (33, "Hake"),
    (34, "Turbot"),
    (35, "Prawn"),
    (36, "John Dory"),
    (37, "Gurnard"),
    (38, "Others"),
]


def scrape_landings(html: str | None = None) -> list[LandingRecord]:
    if html is None:
        logger.info("Fetching %s", URL)
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")

    date = _extract_date(soup)
    if not date:
        logger.warning("Could not extract date from Lerwick page")
        return []

    table = soup.select_one("table.landings-table")
    if not table:
        logger.warning("Could not find landings table on Lerwick page")
        return []

    scraped_at = datetime.utcnow().isoformat()
    records = []

    for row in table.find_all("tr"):
        # Skip header rows
        if row.get("class") and any(
            c in row.get("class", [])
            for c in [
                "ssal-landings-display-reportHeadRow1",
                "ssal-landings-display-reportHeadRow2",
            ]
        ):
            continue

        # Skip total rows
        if "total-row" in row.get("class", []):
            continue

        cells = row.find_all("td")
        if not cells:
            continue

        # Skip location header rows (single cell spanning whole table)
        if len(cells) == 1:
            continue

        # Need at least 39 data cells
        if len(cells) < 39:
            continue

        vessel_name, vessel_code = _parse_vessel(cells[0].get_text(strip=True))
        if not vessel_name:
            continue

        # Graded species — sum all grade columns
        for species, (start, end) in GRADED_SPECIES.items():
            total = sum(_int(cells[i].get_text(strip=True)) for i in range(start, end))
            if total > 0:
                records.append(
                    LandingRecord(
                        date=date,
                        port=PORT,
                        vessel_name=vessel_name,
                        vessel_code=vessel_code,
                        species=species,
                        boxes=total,
                        boxes_msc=0,
                        scraped_at=scraped_at,
                    )
                )

        # Single-species columns
        for col_idx, species in SINGLE_SPECIES:
            boxes = _int(cells[col_idx].get_text(strip=True))
            if boxes > 0:
                records.append(
                    LandingRecord(
                        date=date,
                        port=PORT,
                        vessel_name=vessel_name,
                        vessel_code=vessel_code,
                        species=species,
                        boxes=boxes,
                        boxes_msc=0,
                        scraped_at=scraped_at,
                    )
                )

    logger.info("Scraped %d landing records for %s on %s", len(records), PORT, date)
    return records


def _extract_date(soup: BeautifulSoup) -> str | None:
    """Parse date from h3 text like 'Friday, 13th March 2026'."""
    h3 = soup.find("h3")
    if not h3:
        return None
    text = h3.get_text(strip=True)
    # Strip ordinal suffix: 13th → 13, 1st → 1, 2nd → 2, 3rd → 3
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})", text)
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_vessel(text: str) -> tuple[str, str]:
    """Split 'VESSEL NAME FR123' into ('VESSEL NAME', 'FR123')."""
    parts = text.strip().split()
    if not parts:
        return "", ""
    # Last token is the registration code if it matches pattern (letters+digits)
    if len(parts) >= 2 and re.match(r"^[A-Z]{1,4}\d+$", parts[-1]):
        return " ".join(parts[:-1]), parts[-1]
    return text.strip(), ""


def _int(val: str) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
