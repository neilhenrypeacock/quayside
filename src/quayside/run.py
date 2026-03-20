"""Main entry point: scrape all ports, store, export, process uploads.

Modes
-----
Full run (default):
    python -m quayside
    Scrapes everything from scratch. Ignores cached ETags.

Update run:
    python -m quayside --update
    Re-checks every source using ETag / Last-Modified / content-hash.
    Only re-scrapes ports whose source file has actually changed.
    Safe to run hourly throughout the trading day.
"""

from __future__ import annotations

import logging
import sys
import traceback

from quayside.db import init_db, log_scrape_attempt, upsert_prices
from quayside.export import export_prices_csv
from quayside.http_cache import cached_fetch
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
    log_scrape_attempt("Peterhead", success=err is None and len(prices) > 0,
                       record_count=len(prices),
                       error_type=err["type"] if err else None,
                       error_msg=err["error"] if err else None,
                       data_date=prices[0].date if prices else None)
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
    log_scrape_attempt("Lerwick", success=err is None and len(lerwick_prices) > 0,
                       record_count=len(lerwick_prices),
                       error_type=err["type"] if err else None,
                       error_msg=err["error"] if err else None,
                       data_date=lerwick_prices[0].date if lerwick_prices else None)
    all_prices += lerwick_prices

    # --- Fraserburgh (prices only — dormant, SWFPA stopped publishing) ---
    fraserburgh_prices, err = _run_scraper("Fraserburgh prices", fraserburgh.scrape_prices)
    scraper_status["Fraserburgh prices"] = {
        "records": len(fraserburgh_prices), "error": err, "source": "SWFPA HTML",
    }
    log_scrape_attempt("Fraserburgh", success=err is None and len(fraserburgh_prices) > 0,
                       record_count=len(fraserburgh_prices),
                       error_type=err["type"] if err else None,
                       error_msg=err["error"] if err else None,
                       data_date=fraserburgh_prices[0].date if fraserburgh_prices else None)
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
    log_scrape_attempt("Brixham", success=err is None and len(brixham_prices) > 0,
                       record_count=len(brixham_prices),
                       error_type=err["type"] if err else None,
                       error_msg=err["error"] if err else None,
                       data_date=brixham_prices[0].date if brixham_prices else None)
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
    log_scrape_attempt("Newlyn", success=err is None and len(newlyn_prices) > 0,
                       record_count=len(newlyn_prices),
                       error_type=err["type"] if err else None,
                       error_msg=err["error"] if err else None,
                       data_date=newlyn_prices[0].date if newlyn_prices else None)
    all_prices += newlyn_prices

    # --- Scrabster ---
    scrabster_prices, err = _run_scraper("Scrabster prices", scrabster.scrape_prices)
    scraper_status["Scrabster prices"] = {
        "records": len(scrabster_prices), "error": err, "source": "scrabster.co.uk",
    }
    log_scrape_attempt("Scrabster", success=err is None and len(scrabster_prices) > 0,
                       record_count=len(scrabster_prices),
                       error_type=err["type"] if err else None,
                       error_msg=err["error"] if err else None,
                       data_date=scrabster_prices[0].date if scrabster_prices else None)
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

    # Run quality checks immediately after every successful scrape
    try:
        from quayside.quality import run_quality_checks
        q = run_quality_checks()
        if q["errors"]:
            logger.warning("Quality check: %d errors, %d warnings", q["errors"], q["warns"])
        elif q["warns"]:
            logger.info("Quality check: 0 errors, %d warnings", q["warns"])
        else:
            logger.info("Quality check: all clear")
    except Exception:
        logger.exception("Quality check failed — pipeline result unaffected")

    return 0


_SCRAPER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
}


def update_run() -> int:
    """ETag-aware intraday update.

    Re-checks every scraped source. Only downloads and re-parses files that
    have actually changed since the last run. Upserts any new records and
    regenerates the digest if anything changed.

    Returns 0 (success), 1 (errors), 2 (nothing changed — skipped cleanly).
    """
    logger.info("Quayside update-check starting")
    init_db()

    # SWFPA event discovery is cheap (2 HTML pages) — always re-run it to get
    # the current file URLs, which may change if SWFPA re-uploads a file.
    try:
        swfpa_links = get_swfpa_event_links()
    except Exception as e:
        logger.warning("SWFPA event discovery failed: %s — aborting update", e)
        return 1

    event_date = swfpa_links.get("event_date")

    all_new_prices = []
    changed_ports = []

    # ── SWFPA sources (Peterhead XLS, Brixham PDF, Newlyn PDF) ──

    xls_url = swfpa_links.get("peterhead_xls")
    if xls_url:
        try:
            xls_bytes, is_new = cached_fetch(xls_url, _SCRAPER_HEADERS)
            if is_new:
                logger.info("Peterhead XLS changed — re-scraping")
                prices, err = _run_scraper(
                    "Peterhead prices",
                    lambda: peterhead_prices(xls_bytes=xls_bytes),
                )
                if prices:
                    all_new_prices += prices
                    changed_ports.append("Peterhead")
            else:
                logger.info("Peterhead XLS unchanged — skipping")
        except Exception as e:
            logger.warning("Peterhead update check failed: %s", e)

    brixham_pdf_url = swfpa_links.get("brixham_pdf")
    if brixham_pdf_url:
        try:
            pdf_bytes, is_new = cached_fetch(brixham_pdf_url, _SCRAPER_HEADERS)
            if is_new:
                logger.info("Brixham PDF changed — re-scraping")
                prices, err = _run_scraper(
                    "Brixham prices",
                    lambda: brixham.scrape_prices(
                        pdf_bytes=pdf_bytes, target_date=event_date
                    ),
                )
                if prices:
                    all_new_prices += prices
                    changed_ports.append("Brixham")
            else:
                logger.info("Brixham PDF unchanged — skipping")
        except Exception as e:
            logger.warning("Brixham update check failed: %s", e)

    newlyn_pdf_url = swfpa_links.get("newlyn_pdf")
    if newlyn_pdf_url:
        try:
            pdf_bytes, is_new = cached_fetch(newlyn_pdf_url, _SCRAPER_HEADERS)
            if is_new:
                logger.info("Newlyn PDF changed — re-scraping")
                prices, err = _run_scraper(
                    "Newlyn prices",
                    lambda: newlyn.scrape_prices(
                        pdf_bytes=pdf_bytes, target_date=event_date
                    ),
                )
                if prices:
                    all_new_prices += prices
                    changed_ports.append("Newlyn")
            else:
                logger.info("Newlyn PDF unchanged — skipping")
        except Exception as e:
            logger.warning("Newlyn update check failed: %s", e)

    # ── Lerwick (XLSX generated per-date — stable URL for today) ──
    if event_date:
        lerwick_url = (
            f"https://ssawebportal.azurewebsites.net/daily-prices-generate.php"
            f"?thisdate={event_date}"
        )
        try:
            xlsx_bytes, is_new = cached_fetch(lerwick_url, _SCRAPER_HEADERS)
            if is_new:
                logger.info("Lerwick XLSX changed — re-scraping")
                prices, err = _run_scraper(
                    "Lerwick prices",
                    lambda: lerwick.scrape_prices(
                        target_date=event_date, xlsx_bytes=xlsx_bytes
                    ),
                )
                if prices:
                    all_new_prices += prices
                    changed_ports.append("Lerwick")
            else:
                logger.info("Lerwick XLSX unchanged — skipping")
        except Exception as e:
            logger.warning("Lerwick update check failed: %s", e)

    # ── Scrabster (HTML page) ──
    from quayside.scrapers.scrabster import PRICES_URL as SCRABSTER_URL

    try:
        html_bytes, is_new = cached_fetch(SCRABSTER_URL, _SCRAPER_HEADERS)
        if is_new:
            logger.info("Scrabster page changed — re-scraping")
            prices, err = _run_scraper(
                "Scrabster prices",
                lambda: scrabster.scrape_prices(html=html_bytes.decode("utf-8", errors="replace")),
            )
            if prices:
                all_new_prices += prices
                changed_ports.append("Scrabster")
        else:
            logger.info("Scrabster page unchanged — skipping")
    except Exception as e:
        logger.warning("Scrabster update check failed: %s", e)

    if not all_new_prices:
        logger.info("Update check complete — no source changes detected")
        return 2

    logger.info("Changed ports: %s — upserting %d records", changed_ports, len(all_new_prices))
    upsert_prices(all_new_prices)

    # Export CSVs for changed ports
    by_port: dict[str, list] = {}
    for r in all_new_prices:
        by_port.setdefault(r.port, []).append(r)
    for port, records in by_port.items():
        export_prices_csv(records[0].date, port)

    # Regenerate digest
    try:
        report_path = generate_report()
        logger.info("Digest updated: %s", report_path)
    except Exception:
        logger.exception("Report generation failed")

    logger.info("Update run complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
