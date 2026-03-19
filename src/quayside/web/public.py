"""Public pages blueprint — landing, overview, marketing pages."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template

from quayside.db import (
    get_all_ports,
    get_all_prices_for_date,
    get_last_scrape_info,
    get_latest_rich_date,
)
from quayside.report import build_landing_data
from quayside.web.helpers import build_scrape_info_display

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def landing():
    """Subscriber-focused marketing page."""
    from datetime import date as _date

    date = get_latest_rich_date()
    ld = build_landing_data(date) if date else None
    today_str = _date.today().strftime("%Y-%m-%d")
    is_today = bool(ld and date == today_str)
    ports_today = ld.get("port_count", 0) if is_today else 0
    if is_today and ports_today >= 4:
        data_label = "Today's"
    else:
        data_label = "Yesterday's"
    return render_template(
        "landing.html", ld=ld, data_label=data_label,
        is_today=is_today, ports_today=ports_today,
    )


@public_bp.route("/overview")
def index():
    """Staging hub — links to all screens."""
    ports = get_all_ports(status="active")
    actual_today = datetime.now().strftime("%Y-%m-%d")
    latest = get_latest_rich_date()
    is_fallback = bool(latest and latest != actual_today)
    scrape_info = get_last_scrape_info()
    scrape_info_display = build_scrape_info_display(scrape_info)
    if not is_fallback:
        freshness_status = "live"
    elif scrape_info["last_checked"]:
        hours_since = (datetime.now() - datetime.fromisoformat(scrape_info["last_checked"])).total_seconds() / 3600
        freshness_status = "stale" if hours_since < 4 else "offline"
    else:
        freshness_status = "offline"
    ports_with_today = {
        row[1] for row in get_all_prices_for_date(actual_today)
    } if not is_fallback else set()
    for p in ports:
        p["freshness_status"] = "live" if p["name"] in ports_with_today else freshness_status
    return render_template(
        "index.html",
        ports=ports,
        is_fallback=is_fallback,
        freshness_status=freshness_status,
        scrape_info=scrape_info_display,
        latest_date=latest,
    )


@public_bp.route("/for-ports")
def for_ports():
    """Port-focused marketing and onboarding page."""
    return render_template("for_ports.html")


@public_bp.route("/for-traders")
def for_traders():
    """Buyer and seller focused marketing and membership page."""
    return render_template("for_traders.html")


@public_bp.route("/about")
def about():
    """About Quayside — mission, how it works, port coverage."""
    active_ports = get_all_ports(status="active")
    ports = [
        {
            "name": p["name"],
            "slug": p["slug"],
            "region": p["region"],
            "data": "Prices",
            "method": p.get("data_method", "scraper").replace("scraper", "Automated").replace("upload", "Upload").replace("demo", "Demo"),
        }
        for p in active_ports
        if p.get("data_method") != "demo"
    ]
    return render_template("about.html", ports=ports)


@public_bp.route("/methodology")
def methodology():
    """Data methodology page — explains how prices are calculated."""
    return render_template("methodology.html")
