"""Digest blueprint — daily, weekly, and monthly digest routes."""

from __future__ import annotations

import jinja2
from flask import Blueprint, render_template

from quayside.db import get_latest_rich_date
from quayside.report import build_report_data
from quayside.review import build_monthly_data, build_weekly_data

digest_bp = Blueprint("digest", __name__)

# Digest email template uses a separate Jinja2 env (different folder)
_digest_env = jinja2.Environment(
    loader=jinja2.PackageLoader("quayside", "templates"),
    autoescape=True,
)


@digest_bp.route("/digest")
@digest_bp.route("/digest/<date>")
def digest_page(date: str | None = None):
    """Web version of the daily email digest."""
    if date is None:
        date = get_latest_rich_date()
    if not date:
        return render_template("landing.html")

    data = build_report_data(date)
    digest_template = _digest_env.get_template("digest.html")
    digest_html = digest_template.render(**data)
    return render_template(
        "digest_wrapper.html", digest_html=digest_html, date=date,
        generated_at=data.get("generated_at"), page_title="Yesterday's Digest",
        auto_refresh_interval=10,
    )


@digest_bp.route("/digest/yesterday")
def digest_yesterday():
    """Show the most recent completed trading day digest."""
    date = get_latest_rich_date()
    if not date:
        return render_template("landing.html")
    data = build_report_data(date)
    digest_template = _digest_env.get_template("digest.html")
    digest_html = digest_template.render(**data)
    return render_template(
        "digest_wrapper.html", digest_html=digest_html, date=date,
        generated_at=data.get("generated_at"), page_title="Yesterday's Digest",
        auto_refresh_interval=10,
    )


@digest_bp.route("/digest/today")
def digest_today():
    """Show today's digest, updating as ports report throughout the day."""
    from datetime import date as _date

    today = _date.today().strftime("%Y-%m-%d")
    data = build_report_data(today)
    digest_template = _digest_env.get_template("digest.html")
    digest_html = digest_template.render(**data)
    return render_template(
        "digest_wrapper.html", digest_html=digest_html, date=today,
        generated_at=data.get("generated_at"), page_title="Today's Digest",
        auto_refresh_interval=5,
    )


@digest_bp.route("/digest/weekly")
@digest_bp.route("/digest/weekly/<date>")
def weekly_digest(date: str | None = None):
    """Weekly review — 5-day snapshot with movers, benchmarks, spreads."""
    data = build_weekly_data(date)
    return render_template("weekly.html", data=data)


@digest_bp.route("/digest/monthly")
@digest_bp.route("/digest/monthly/<year_month>")
def monthly_digest(year_month: str | None = None):
    """Monthly review — trends, volatility, reliability, availability."""
    data = build_monthly_data(year_month)
    return render_template("monthly.html", data=data)
