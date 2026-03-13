"""Scrape Peterhead fish landings from peterheadport.co.uk."""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from quayside.models import LandingRecord

logger = logging.getLogger(__name__)

URL = "https://www.peterheadport.co.uk/fish-auction/"
PORT = "Peterhead"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}


def scrape_landings(html: str | None = None) -> list[LandingRecord]:
    """Scrape today's landings. Pass html for testing, otherwise fetches live."""
    if html is None:
        logger.info("Fetching %s", URL)
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    date = _extract_date(soup)
    if not date:
        logger.error("Could not extract date from page")
        return []

    table = soup.find("table", id="fish-auction-table")
    if not table:
        logger.error("Could not find fish-auction-table")
        return []

    headers = [th.get_text(strip=True) for th in table.find("thead").find_all("th")]
    # headers[0] = "Ship Name", headers[1] = "Total Boxes", headers[2:] = species
    species_names = headers[2:]  # Should match LANDING_SPECIES

    scraped_at = datetime.now().isoformat()
    records = []

    rows = table.find_all("tr")
    i = 0
    while i < len(rows):
        row = rows[i]
        # Skip header row
        if row.find("th"):
            i += 1
            continue

        # Check if this is a vessel row (has a td with rowspan)
        name_cell = row.find("td", attrs={"rowspan": True})
        if name_cell is None:
            # Could be the MSC row (handled below) or the Totals row
            td_text = row.find("td")
            if td_text and "Totals" in td_text.get_text():
                break
            i += 1
            continue

        # Parse vessel name and code
        vessel_text = name_cell.get_text(strip=True)
        vessel_name, vessel_code = _parse_vessel(vessel_text)

        # Regular row: all tds after the name cell
        tds = row.find_all("td")
        # tds[0] = name (rowspan), tds[1] = Total Boxes, tds[2:] = species
        regular_boxes = _parse_box_values(tds[1:])  # skip name cell

        # MSC row: next row (class uk-background-muted)
        msc_boxes = [0] * len(species_names)
        if i + 1 < len(rows):
            msc_row = rows[i + 1]
            if (
                "uk-background-muted" in msc_row.get("class", [])
                or msc_row.get("bgcolor", "").lower() == "#cccccc"
            ):
                msc_tds = msc_row.find_all("td")
                msc_boxes = _parse_box_values(msc_tds)
                i += 1  # skip the MSC row

        # Create records for each species (skip zeros)
        for j, species in enumerate(species_names):
            # regular_boxes[0] = Total Boxes, regular_boxes[1:] = per species
            reg = regular_boxes[j + 1] if j + 1 < len(regular_boxes) else 0
            msc = msc_boxes[j + 1] if j + 1 < len(msc_boxes) else 0
            if reg > 0 or msc > 0:
                records.append(
                    LandingRecord(
                        date=date,
                        port=PORT,
                        vessel_name=vessel_name,
                        vessel_code=vessel_code,
                        species=species,
                        boxes=reg,
                        boxes_msc=msc,
                        scraped_at=scraped_at,
                    )
                )

        i += 1

    logger.info("Scraped %d landing records for %s on %s", len(records), PORT, date)
    return records


def _extract_date(soup: BeautifulSoup) -> str | None:
    """Extract date from 'Fish for sale on DD/MM/YYYY' heading."""
    h5 = soup.find("h5", string=re.compile(r"Fish for sale on"))
    if h5:
        match = re.search(r"(\d{2}/\d{2}/\d{4})", h5.get_text())
        if match:
            d, m, y = match.group(1).split("/")
            return f"{y}-{m}-{d}"

    # Fallback: "Updated on: DD/MM/YYYY HH:MM:SS"
    updated = soup.find(class_="updated-on")
    if updated:
        match = re.search(r"(\d{2}/\d{2}/\d{4})", updated.get_text())
        if match:
            d, m, y = match.group(1).split("/")
            return f"{y}-{m}-{d}"

    return None


def _parse_vessel(text: str) -> tuple[str, str]:
    """Split 'NORLAN BF362' into ('NORLAN', 'BF362').

    Vessel codes are typically 2-3 letters + digits, at the end.
    Some have (C) suffix for certification.
    """
    text = re.sub(r"\s*\(C\)\s*$", "", text.strip())
    match = re.match(r"^(.+?)\s+([A-Z]{1,4}\d+)$", text)
    if match:
        return match.group(1).strip(), match.group(2)
    return text, ""


def _parse_box_values(tds: list) -> list[int]:
    """Extract integer values from a list of <td> elements."""
    values = []
    for td in tds:
        text = td.get_text(strip=True)
        try:
            values.append(int(text))
        except (ValueError, TypeError):
            values.append(0)
    return values
