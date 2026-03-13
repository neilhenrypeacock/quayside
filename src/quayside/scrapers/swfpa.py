"""Scrape Peterhead auction prices from SWFPA daily fish prices (Excel)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import requests
import xlrd
from bs4 import BeautifulSoup

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)

SWFPA_URL = "https://swfpa.com/downloads/daily-fish-prices/"
PORT = "Peterhead"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}


def get_swfpa_event_links(target_date: str | None = None) -> dict:
    """Fetch SWFPA calendar once and return all relevant file links.

    Returns dict with keys: 'peterhead_xls', 'brixham_pdf', 'event_date'
    Any value may be None if not found.
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    logger.info("Looking for SWFPA event links for %s", target_date)
    empty = {"peterhead_xls": None, "brixham_pdf": None, "event_date": None}

    # Step 1: Get event list
    resp = requests.get(SWFPA_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    match = re.search(r"(?:var|window\.)\s*customQuery\s*=\s*(\[.*?\]);", resp.text, re.DOTALL)
    if not match:
        logger.error("Could not find customQuery in SWFPA page")
        return empty

    events = json.loads(match.group(1))
    logger.info("Found %d events on SWFPA calendar", len(events))

    # Step 2: Find matching event
    event = None
    for e in events:
        if e.get("start") == target_date:
            event = e
            break

    if event is None:
        candidates = [e for e in events if e.get("start", "") <= target_date]
        if candidates:
            event = max(candidates, key=lambda e: e["start"])
            logger.info("No exact match for %s, using %s", target_date, event["start"])

    if event is None:
        logger.warning("No SWFPA event found for or before %s", target_date)
        return empty

    event_id = event["id"]
    event_date = event.get("start")
    logger.info("Found event %d: %s (%s)", event_id, event.get("title", ""), event_date)

    # Step 3: Fetch event detail and extract all file links
    detail_url = f"{SWFPA_URL}?p={event_id}"
    resp = requests.get(detail_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    result = {
        "peterhead_xls": None,
        "brixham_pdf": None,
        "newlyn_pdf": None,
        "event_date": event_date,
    }

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "peterhead" in href.lower() and href.endswith(".xls"):
            logger.info("Found Peterhead XLS: %s", href)
            result["peterhead_xls"] = href
        elif "daily-fish-sales" in href.lower() and href.endswith(".pdf"):
            logger.info("Found Brixham PDF: %s", href)
            result["brixham_pdf"] = href
        elif (
            href.endswith(".pdf")
            and result["brixham_pdf"] != href
            and "peterhead" not in href.lower()
        ):
            # Newlyn PDFs are named by date (e.g. "9TH.pdf", "6th.pdf")
            logger.info("Found Newlyn PDF: %s", href)
            result["newlyn_pdf"] = href

    return result


def find_todays_xls_url(target_date: str | None = None) -> str | None:
    """Find the Peterhead XLS URL for today (or target_date YYYY-MM-DD)."""
    return get_swfpa_event_links(target_date)["peterhead_xls"]


def scrape_prices(xls_url: str | None = None, xls_bytes: bytes | None = None) -> list[PriceRecord]:
    """Parse Peterhead price data from XLS. Pass xls_bytes for testing."""
    if xls_bytes is None:
        if xls_url is None:
            xls_url = find_todays_xls_url()
        if xls_url is None:
            return []
        logger.info("Downloading %s", xls_url)
        resp = requests.get(xls_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        xls_bytes = resp.content

    wb = xlrd.open_workbook(file_contents=xls_bytes)
    sheet = wb.sheet_by_name("Daily Prices")

    # Extract date from row 5, col 0 (format: DD.MM.YYYY)
    date_str = str(sheet.cell_value(5, 0)).strip()
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", date_str)
    if not match:
        logger.error("Could not parse date from XLS: %r", date_str)
        return []
    date = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"

    scraped_at = datetime.now().isoformat()
    records = []
    current_species = None
    is_round = False

    for row_idx in range(7, sheet.nrows):
        col0 = str(sheet.cell_value(row_idx, 0)).strip()
        col1 = str(sheet.cell_value(row_idx, 1)).strip()

        # Skip the header row and empty/footer rows
        if col1 == "Grade/Size" or "Supplied By" in col0:
            continue

        # Check for "RND" prefix (round variant)
        if col0 == "RND":
            is_round = True
            # col1 might have a grade on the same row
            if col1 and re.match(r"^[AB]\d", col1):
                grade = col1
                low, high, avg = _read_prices(sheet, row_idx)
                species_name = f"{current_species} Round" if current_species else "Round"
                if _has_any_price(low, high, avg):
                    records.append(
                        PriceRecord(
                            date=date,
                            port=PORT,
                            species=species_name,
                            grade=grade,
                            price_low=low,
                            price_high=high,
                            price_avg=avg,
                            scraped_at=scraped_at,
                        )
                    )
            continue

        # New species header
        if col0 and col0 != "RND":
            is_round = False
            # Check if this is a single-row species (prices directly on this row)
            low, high, avg = _read_prices(sheet, row_idx)

            if col1 == "" and _has_any_price(low, high, avg):
                # Single-row species: Catfish Scottish, Turbot, Halibut, Brill, Witches, Tusk, Skate
                if low is not None or high is not None:
                    # Has LOW/HIGH → actual price data
                    records.append(
                        PriceRecord(
                            date=date,
                            port=PORT,
                            species=col0,
                            grade="ALL",
                            price_low=low,
                            price_high=high,
                            price_avg=avg,
                            scraped_at=scraped_at,
                        )
                    )
                # If only AVG → species average summary row, skip
                current_species = col0
            elif col1 == "":
                # Species header with no prices on this row
                current_species = col0
            continue

        # Grade row (col0 empty, col1 has grade like A1, A2, etc.)
        if col1 and re.match(r"^[AB]\d", col1):
            low, high, avg = _read_prices(sheet, row_idx)
            grade = col1

            # Determine species name
            species_name = current_species or "Unknown"
            if is_round:
                species_name = f"{current_species} Round"

            # Handle Haddock sub-variants: "A4 - Chipper", "A4 - Metro", "A4 - Round"
            if " - " in grade:
                parts = grade.split(" - ", 1)
                grade = f"{parts[0]}-{parts[1]}"

            if _has_any_price(low, high, avg):
                records.append(
                    PriceRecord(
                        date=date,
                        port=PORT,
                        species=species_name,
                        grade=grade,
                        price_low=low,
                        price_high=high,
                        price_avg=avg,
                        scraped_at=scraped_at,
                    )
                )

    logger.info("Scraped %d price records for %s on %s", len(records), PORT, date)
    return records


def _read_prices(sheet, row_idx: int) -> tuple:
    """Read LOW (col 3), HIGH (col 4), AVG (col 5) from a row."""

    def _val(col):
        v = sheet.cell_value(row_idx, col)
        if isinstance(v, (int, float)) and v > 0:
            return round(v, 2)
        return None

    return _val(3), _val(4), _val(5)


def _has_any_price(low, high, avg) -> bool:
    return any(v is not None for v in (low, high, avg))
