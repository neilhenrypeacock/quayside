"""Main entry point: scrape all ports, store, export, process uploads."""

from __future__ import annotations

import logging
import sys
import traceback

from quayside.db import init_db, upsert_prices
from quayside.export import export_prices_csv
from quayside.ports import seed_ports
from quayside.report import generate_report
from quayside.scrapers import brixham, cfpo, fraserburgh, lerwick, newlyn, scrabster
from quayside.scrapers.swfpa import get_swfpa_event_links
from quayside.scrapers.swfpa import scrape_prices as peterhead_prices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _run_scraper(name, fn):
    """Run a scraper function, return results or [] on failure.

    Captures the error detail for diagnostic reporting.
    Returns (results, error_info) tuple.
    """
    try:
        results = fn()
        return results or [], None
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("%s failed", name)
        return [], {"error": str(e), "type": type(e).__name__, "traceback": tb}


def main() -> int:
    logger.info("Quayside pipeline starting")
    init_db()
    seed_ports()

    all_prices = []
    # Track scraper health: {name: {records: N, error: str|None, source: str}}
    scraper_status = {}

    # --- SWFPA event discovery (once for all SWFPA-sourced ports) ---
    try:
        swfpa_links = get_swfpa_event_links()
    except Exception as e:
        logger.exception("SWFPA event discovery failed")
        swfpa_links = {
            "peterhead_xls": None,
            "brixham_pdf": None,
            "newlyn_pdf": None,
            "event_date": None,
        }
        scraper_status["SWFPA discovery"] = {
            "records": 0, "error": str(e), "source": "swfpa.com",
        }

    event_date = swfpa_links.get("event_date")

    # --- Peterhead ---
    prices, err = _run_scraper(
        "Peterhead prices",
        lambda: peterhead_prices(xls_url=swfpa_links.get("peterhead_xls")),
    )
    scraper_status["Peterhead prices"] = {
        "records": len(prices), "error": err, "source": "SWFPA XLS",
    }
    all_prices += prices

    # --- Lerwick (prices from SSA portal XLSX) ---
    lerwick_prices, err = _run_scraper(
        "Lerwick prices",
        lambda: lerwick.scrape_prices(target_date=event_date),
    )
    scraper_status["Lerwick prices"] = {
        "records": len(lerwick_prices), "error": err,
        "source": "ssawebportal.azurewebsites.net",
    }
    all_prices += lerwick_prices

    # --- Fraserburgh (prices only — dormant, SWFPA stopped publishing) ---
    fraserburgh_prices, err = _run_scraper("Fraserburgh prices", fraserburgh.scrape_prices)
    scraper_status["Fraserburgh prices"] = {
        "records": len(fraserburgh_prices), "error": err, "source": "SWFPA HTML",
    }
    all_prices += fraserburgh_prices

    # --- Brixham ---
    brixham_prices, err = _run_scraper(
        "Brixham prices",
        lambda: brixham.scrape_prices(
            pdf_url=swfpa_links.get("brixham_pdf"),
            target_date=event_date,
        ),
    )
    scraper_status["Brixham prices"] = {
        "records": len(brixham_prices), "error": err, "source": "SWFPA PDF",
    }
    all_prices += brixham_prices

    # --- Newlyn (SWFPA primary, CFPO fallback) ---
    newlyn_prices, err = _run_scraper(
        "Newlyn prices",
        lambda: newlyn.scrape_prices(
            pdf_url=swfpa_links.get("newlyn_pdf"),
            target_date=event_date,
        ),
    )
    newlyn_source = "SWFPA PDF"
    if not newlyn_prices:
        if err:
            logger.info("SWFPA Newlyn failed (%s) — trying CFPO fallback", err["error"])
        else:
            logger.info("SWFPA had no Newlyn data — trying CFPO fallback")
        newlyn_prices, err = _run_scraper(
            "Newlyn prices (CFPO)",
            lambda: cfpo.scrape_prices(target_date=event_date),
        )
        newlyn_source = "CFPO PDF"
    scraper_status["Newlyn prices"] = {
        "records": len(newlyn_prices), "error": err, "source": newlyn_source,
    }
    all_prices += newlyn_prices

    # --- Scrabster ---
    scrabster_prices, err = _run_scraper("Scrabster prices", scrabster.scrape_prices)
    scraper_status["Scrabster prices"] = {
        "records": len(scrabster_prices), "error": err, "source": "scrabster.co.uk",
    }
    all_prices += scrabster_prices

    # --- Scraper health summary ---
    logger.info("--- Scraper health ---")
    for name, status in scraper_status.items():
        count = status["records"]
        err = status["error"]
        source = status["source"]
        if err:
            err_msg = err["error"] if isinstance(err, dict) else str(err)
            logger.warning("  %-25s  %3d records  FAILED  (%s) — %s", name, count, source, err_msg)
        elif count == 0:
            logger.warning("  %-25s  %3d records  EMPTY   (%s)", name, count, source)
        else:
            logger.info("  %-25s  %3d records  OK      (%s)", name, count, source)

    failed = [n for n, s in scraper_status.items() if s["error"]]
    empty = [n for n, s in scraper_status.items() if not s["error"] and s["records"] == 0]
    if failed:
        logger.warning("Failed scrapers: %s", ", ".join(failed))
    if empty:
        logger.info("Empty scrapers (no data today): %s", ", ".join(empty))

    # Store
    if all_prices:
        count = upsert_prices(all_prices)
        logger.info("Stored %d price records total", count)
    else:
        logger.warning("No price records scraped")

    if not all_prices:
        logger.error("All scrapers returned zero records")
        return 1

    # Export CSVs per port
    for port, records in [
        ("Peterhead", prices),
        ("Lerwick", lerwick_prices),
        ("Fraserburgh", fraserburgh_prices),
        ("Brixham", brixham_prices),
        ("Newlyn", newlyn_prices),
        ("Scrabster", scrabster_prices),
    ]:
        if records:
            export_prices_csv(records[0].date, port)

    # Generate HTML digest report
    report_path = None
    try:
        report_path = generate_report()
        logger.info("Report: %s", report_path)
    except Exception:
        logger.exception("Report generation failed")

    # --- Process email uploads (if configured) ---
    try:
        from quayside.ingest import poll_mailbox

        uploads = poll_mailbox()
        if uploads:
            logger.info("Processed %d email uploads", len(uploads))
            # Send confirmation emails
            from quayside.confirm import send_confirmation_email
            for upload_info in uploads:
                try:
                    send_confirmation_email(
                        upload_info["upload_id"],
                        upload_info["records"],
                    )
                except Exception:
                    logger.exception(
                        "Failed to send confirmation for upload %d",
                        upload_info["upload_id"],
                    )
    except ValueError:
        logger.debug("Email ingestion not configured — skipping")
    except Exception:
        logger.exception("Email ingestion failed")

    # --- Auto-publish stale uploads (pending > 2 hours) ---
    try:
        from quayside.confirm import auto_publish_stale_uploads

        auto_count = auto_publish_stale_uploads()
        if auto_count:
            logger.info("Auto-published %d stale uploads", auto_count)
    except Exception:
        logger.exception("Auto-publish check failed")

    # Email digest (only if configured via env vars)
    if report_path:
        try:
            from quayside.email import send_digest

            date = report_path.stem.replace("digest_", "")
            send_digest(report_path, date)
        except ValueError:
            logger.debug("Email not configured — skipping (set QUAYSIDE_SMTP_* env vars)")
        except Exception:
            logger.exception("Email delivery failed")

    logger.info("Pipeline complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
