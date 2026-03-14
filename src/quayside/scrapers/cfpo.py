"""Scrape Newlyn fish prices from CFPO (Cornish Fish Producers Organisation).

CFPO publishes daily Newlyn market prices as PDFs at:
    https://www.cfpo.org.uk/wp-content/uploads/YYYY/MM/{DAY}{SUFFIX}.pdf

e.g. https://www.cfpo.org.uk/wp-content/uploads/2026/03/9TH.pdf

The PDF format is identical to the SWFPA Newlyn PDFs, so we delegate
parsing to the existing newlyn.scrape_prices() function.

This serves as a backup/alternative source when SWFPA doesn't provide
a Newlyn PDF for a given day.
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests

from quayside.models import PriceRecord
from quayside.scrapers.newlyn import scrape_prices as newlyn_parse

logger = logging.getLogger(__name__)

CFPO_BASE = "https://www.cfpo.org.uk/wp-content/uploads"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}


def _ordinal_suffix(day: int) -> str:
    """Return uppercase ordinal suffix for a day number (1ST, 2ND, 3RD, 4TH…)."""
    if 11 <= day <= 13:
        return "TH"
    last = day % 10
    if last == 1:
        return "ST"
    if last == 2:
        return "ND"
    if last == 3:
        return "RD"
    return "TH"


def build_cfpo_url(target_date: str) -> str:
    """Build the CFPO PDF URL for a given date (YYYY-MM-DD)."""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    suffix = _ordinal_suffix(dt.day)
    return f"{CFPO_BASE}/{dt.year}/{dt.month:02d}/{dt.day}{suffix}.pdf"


def scrape_prices(target_date: str | None = None) -> list[PriceRecord]:
    """Scrape Newlyn prices from the CFPO daily PDF.

    Constructs the expected URL from the date and downloads the PDF.
    Delegates parsing to the existing newlyn scraper.
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    url = build_cfpo_url(target_date)
    logger.info("Trying CFPO Newlyn PDF: %s", url)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.info("CFPO PDF not available for %s: %s", target_date, e)
        return []

    # Delegate to existing Newlyn parser
    records = newlyn_parse(pdf_bytes=resp.content, target_date=target_date)
    logger.info("CFPO returned %d Newlyn price records for %s", len(records), target_date)
    return records
