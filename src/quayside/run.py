"""Main entry point: scrape all ports, store, export."""

from __future__ import annotations

import logging
import sys

from quayside.db import init_db, upsert_landings, upsert_prices
from quayside.export import export_landings_csv, export_prices_csv
from quayside.report import generate_report
from quayside.scrapers import brixham, fraserburgh, lerwick, newlyn, scrabster
from quayside.scrapers.peterhead import scrape_landings as peterhead_landings
from quayside.scrapers.swfpa import get_swfpa_event_links, scrape_prices as peterhead_prices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _run_scraper(name, fn):
    """Run a scraper function, return results or [] on failure."""
    try:
        results = fn()
        return results or []
    except Exception:
        logger.exception("%s failed", name)
        return []


def main() -> int:
    logger.info("Quayside pipeline starting")
    init_db()

    all_landings = []
    all_prices = []

    # --- SWFPA event discovery (once for all SWFPA-sourced ports) ---
    try:
        swfpa_links = get_swfpa_event_links()
    except Exception:
        logger.exception("SWFPA event discovery failed")
        swfpa_links = {"peterhead_xls": None, "brixham_pdf": None, "newlyn_pdf": None, "event_date": None}

    event_date = swfpa_links.get("event_date")

    # --- Peterhead ---
    landings = _run_scraper("Peterhead landings", peterhead_landings)
    prices = _run_scraper(
        "Peterhead prices",
        lambda: peterhead_prices(xls_url=swfpa_links.get("peterhead_xls")),
    )
    all_landings += landings
    all_prices += prices

    # --- Lerwick ---
    lerwick_landings = _run_scraper("Lerwick landings", lerwick.scrape_landings)
    all_landings += lerwick_landings

    # --- Fraserburgh (prices only — landings need Playwright, see ROADMAP) ---
    fraserburgh_prices = _run_scraper("Fraserburgh prices", fraserburgh.scrape_prices)
    all_prices += fraserburgh_prices

    # --- Brixham ---
    brixham_prices = _run_scraper(
        "Brixham prices",
        lambda: brixham.scrape_prices(
            pdf_url=swfpa_links.get("brixham_pdf"),
            target_date=event_date,
        ),
    )
    all_prices += brixham_prices

    # --- Newlyn ---
    newlyn_prices = _run_scraper(
        "Newlyn prices",
        lambda: newlyn.scrape_prices(
            pdf_url=swfpa_links.get("newlyn_pdf"),
            target_date=event_date,
        ),
    )
    all_prices += newlyn_prices

    # --- Scrabster ---
    scrabster_prices = _run_scraper("Scrabster prices", scrabster.scrape_prices)
    all_prices += scrabster_prices

    # Store
    if all_landings:
        count = upsert_landings(all_landings)
        logger.info("Stored %d landing records total", count)
    else:
        logger.warning("No landing records scraped")

    if all_prices:
        count = upsert_prices(all_prices)
        logger.info("Stored %d price records total", count)
    else:
        logger.warning("No price records scraped")

    if not all_landings and not all_prices:
        logger.error("All scrapers returned zero records")
        return 1

    # Export CSVs per port
    for port, records in [("Peterhead", landings), ("Lerwick", lerwick_landings)]:
        if records:
            export_landings_csv(records[0].date, port)

    for port, records in [
        ("Peterhead", prices),
        ("Fraserburgh", fraserburgh_prices),
        ("Brixham", brixham_prices),
        ("Newlyn", newlyn_prices),
        ("Scrabster", scrabster_prices),
    ]:
        if records:
            export_prices_csv(records[0].date, port)

    # Generate HTML digest report
    try:
        report_path = generate_report()
        logger.info("Report: %s", report_path)
    except Exception:
        logger.exception("Report generation failed")

    logger.info("Pipeline complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
