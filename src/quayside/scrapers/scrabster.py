"""Scrape Scrabster fish prices from scrabster.co.uk.

Source: scrabster.co.uk/port-information/fish-prices/
Format: HTML table with columns: Species, Number of Boxes, Bottom Price, Top Price
Prices are per kg. Updated daily.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)

PORT = "Scrabster"
PRICES_URL = "https://scrabster.co.uk/port-information/fish-prices/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}


def scrape_prices(html: str | None = None) -> list[PriceRecord]:
    """Scrape Scrabster prices from the port website."""
    if html is None:
        try:
            resp = requests.get(PRICES_URL, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            logger.warning("Could not fetch Scrabster prices: %s", e)
            return []

    soup = BeautifulSoup(html, "lxml")

    date = _extract_date(soup)
    if not date:
        logger.warning("Could not determine date for Scrabster prices")
        return []

    scraped_at = datetime.utcnow().isoformat()
    records = []

    tables = soup.find_all("table")
    # The prices table is the one with "Species" in the header row
    table = None
    for t in tables:
        first_row = t.find("tr")
        if first_row and "species" in first_row.get_text().lower():
            table = t
            break

    if not table:
        logger.warning("No prices table found on Scrabster page")
        return []

    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        species = cells[0].get_text(strip=True)
        if not species or species.lower() in ("species", "total", "totals"):
            continue

        boxes_str = cells[1].get_text(strip=True)
        boxes = _parse_int(boxes_str)

        bottom_str = cells[2].get_text(strip=True)
        top_str = cells[3].get_text(strip=True)

        bottom = _parse_price(bottom_str)
        top = _parse_price(top_str)

        if bottom is None and top is None:
            continue

        # Calculate average from bottom/top when both available
        avg = None
        if bottom is not None and top is not None:
            avg = round((bottom + top) / 2, 2)
        elif bottom is not None:
            avg = bottom
        elif top is not None:
            avg = top

        records.append(
            PriceRecord(
                date=date,
                port=PORT,
                species=species,
                grade="ALL",
                price_low=bottom,
                price_high=top,
                price_avg=avg,
                scraped_at=scraped_at,
                boxes=boxes,
            )
        )

    logger.info("Scraped %d price records for %s on %s", len(records), PORT, date)
    return records


def _parse_int(s: str) -> int | None:
    """Parse an integer string, returning None for empty/invalid."""
    s = s.strip().replace(",", "")
    if not s or s == "-":
        return None
    try:
        v = int(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_price(s: str) -> float | None:
    """Parse a price string, returning None for empty/invalid."""
    s = s.strip().replace(",", "")
    if not s or s == "-":
        return None
    try:
        v = float(s)
        return round(v, 2) if v > 0 else None
    except ValueError:
        return None


def _extract_date(soup: BeautifulSoup) -> str | None:
    """Extract date from page heading like 'Fish Prices for 12/03/2026'."""
    text = soup.get_text()
    # DD/MM/YYYY after "for" or "prices"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        try:
            dt = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None
