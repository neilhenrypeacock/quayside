"""Scrape Fraserburgh fish prices from SWFPA HTML files.

NOTE: SWFPA uploads HTML price files for Fraserburgh at a predictable URL pattern.
As of March 2026 these are not linked from the SWFPA event calendar (unlike Peterhead XLS),
but the files may still be uploaded. This scraper tries the URL directly and fails
gracefully if unavailable.

Fraserburgh landings are currently inaccessible (embedded as a Google Drive PDF iframe
on fraserburgh-harbour.co.uk). See ROADMAP.md Phase 2 notes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)

PORT = "Fraserburgh"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}
# URL pattern: Fraserburgh-DD.MM.html
SWFPA_HTML_PATTERN = (
    "https://swfpa.com/wp-content/uploads/{year}/{month:02d}/Fraserburgh-{day:02d}.{month:02d}.html"
)


def find_fraserburgh_html_url(target_date: str | None = None) -> str | None:
    """Try to find a Fraserburgh HTML price file for target_date or recent days."""
    dt = datetime.strptime(target_date, "%Y-%m-%d") if target_date else datetime.utcnow()

    # Try today and the previous 3 trading days
    for days_back in range(4):
        candidate = dt - timedelta(days=days_back)
        url = SWFPA_HTML_PATTERN.format(
            year=candidate.year,
            month=candidate.month,
            day=candidate.day,
        )
        try:
            resp = requests.head(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                logger.info("Found Fraserburgh HTML: %s", url)
                return url
        except requests.RequestException:
            continue

    logger.info(
        "No Fraserburgh HTML price file found on SWFPA for %s (tried 4 days back)", dt.date()
    )
    return None


def scrape_prices(
    html_url: str | None = None,
    html_bytes: bytes | None = None,
    target_date: str | None = None,
) -> list[PriceRecord]:
    """Scrape Fraserburgh prices from a SWFPA HTML file."""

    if html_bytes is None:
        if html_url is None:
            html_url = find_fraserburgh_html_url(target_date)
        if html_url is None:
            return []
        try:
            resp = requests.get(html_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            html_bytes = resp.content
        except requests.RequestException as e:
            logger.warning("Could not fetch Fraserburgh HTML: %s", e)
            return []

    html = html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    date = _extract_date(soup)
    if not date:
        logger.warning("Could not extract date from Fraserburgh HTML")
        return []

    table = soup.find("table")
    if not table:
        logger.warning("No table found in Fraserburgh HTML")
        return []

    scraped_at = datetime.utcnow().isoformat()
    records = []

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        species_raw = cells[0].get_text(strip=True)
        price_raw = cells[1].get_text(strip=True).replace("\xa0", "").strip()

        if not species_raw or not price_raw:
            continue

        # Normalise species and grade from names like "Haddock Round", "Haddock Gutted"
        species, grade = _parse_species_grade(species_raw)
        if not species:
            continue

        price = _float(price_raw)
        if price is None:
            continue

        records.append(
            PriceRecord(
                date=date,
                port=PORT,
                species=species,
                grade=grade,
                price_low=None,
                price_high=None,
                price_avg=price,
                scraped_at=scraped_at,
            )
        )

    logger.info("Scraped %d price records for %s on %s", len(records), PORT, date)
    return records


def _extract_date(soup: BeautifulSoup) -> str | None:
    """Extract date from text like 'Date : 21st October 2022'."""
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Date\s*:\s*(\d+)(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})", text)
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_species_grade(raw: str) -> tuple[str, str]:
    """Split 'Haddock Round' → ('Haddock', 'Round'), 'Cod' → ('Cod', 'ALL')."""
    suffixes = {"Round": "Round", "Gutted": "Gutted", "Rnd": "Round", "Gtd": "Gutted"}
    parts = raw.split()
    if len(parts) >= 2 and parts[-1] in suffixes:
        return " ".join(parts[:-1]), suffixes[parts[-1]]
    return raw.strip(), "ALL"


def _float(val: str) -> float | None:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
