"""Flask application — port dashboards, upload form, confirmation pages.

Run with: python -m quayside.web.app
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import jinja2
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from quayside.confirm import generate_confirm_token, get_upload_for_token
from quayside.db import (
    confirm_upload,
    create_upload,
    get_all_ports,
    get_latest_date,
    get_market_averages_for_date,
    get_port,
    get_port_by_token,
    get_port_prices_history,
    get_prices_by_date,
    get_upload,
    init_db,
    log_correction,
    seed_demo_data,
    upsert_prices_with_upload,
)
from quayside.extractors import extract_from_file
from quayside.models import PriceRecord
from quayside.ports import seed_ports
from quayside.report import build_report_data
from quayside.species import normalise_species

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
    )
    app.secret_key = os.environ.get("QUAYSIDE_SECRET_KEY", "dev-secret-change-me")

    # Digest email template uses a separate Jinja2 env (different folder)
    _digest_env = jinja2.Environment(
        loader=jinja2.PackageLoader("quayside", "templates"),
        autoescape=True,
    )

    with app.app_context():
        init_db()
        seed_ports()
        seed_demo_data()

    @app.route("/")
    def index():
        """Staging hub — links to all screens."""
        ports = get_all_ports(status="active")
        return render_template("index.html", ports=ports)

    @app.route("/landing")
    def landing():
        """Subscriber-focused marketing page."""
        return render_template("landing.html")

    @app.route("/for-ports")
    def for_ports():
        """Port-focused marketing and onboarding page."""
        return render_template("for_ports.html")

    @app.route("/digest")
    @app.route("/digest/<date>")
    def digest_page(date: str | None = None):
        """Web version of the daily email digest."""
        if date is None:
            date = get_latest_date()
        if not date:
            return render_template("landing.html")  # No data yet

        data = build_report_data(date)
        digest_template = _digest_env.get_template("digest.html")
        digest_html = digest_template.render(**data)
        # Wrap in a simple page with nav
        return render_template("digest_wrapper.html", digest_html=digest_html, date=date)

    @app.route("/port/<slug>")
    def port_dashboard(slug: str):
        """Port dashboard — shows their data + market position."""
        port = get_port(slug)
        if not port:
            return "Port not found", 404

        # Auth check: magic link token in query string or cookie
        token = request.args.get("token") or request.cookies.get(f"port_{slug}")
        if token:
            valid_port = get_port_by_token(token)
            if not valid_port or valid_port["slug"] != slug:
                return "Invalid or expired link", 403

        date = get_latest_date() or datetime.now().strftime("%Y-%m-%d")

        # Get this port's prices for today
        port_prices = get_prices_by_date(date, port["name"])

        # Get market averages for comparison
        market = get_market_averages_for_date(date)

        # Normalise and build dashboard data
        today_data = []
        for row in port_prices:
            _, _, species, grade, low, high, avg = row
            canonical = normalise_species(species)
            market_info = market.get(canonical, {})

            position = None
            if avg and market_info.get("port_count", 0) >= 2:
                market_avg = market_info["avg"]
                market_min = market_info["min"]
                market_max = market_info["max"]
                is_best = avg >= market_max
                is_below = avg < market_avg * 0.95  # 5% below market avg
                position = {
                    "market_avg": round(market_avg, 2),
                    "market_min": round(market_min, 2),
                    "market_max": round(market_max, 2),
                    "port_count": market_info["port_count"],
                    "is_best": is_best,
                    "is_below": is_below,
                    "pct_of_range": _pct_in_range(avg, market_min, market_max),
                }

            today_data.append({
                "species": canonical,
                "grade": grade,
                "price_low": low,
                "price_high": high,
                "price_avg": avg,
                "position": position,
            })

        # Get 30-day history for trend chart
        history = get_port_prices_history(port["name"], days=30)
        trend_data = _build_trend_data(history)

        response = app.make_response(render_template(
            "dashboard.html",
            port=port,
            date=date,
            today_data=today_data,
            trend_data=json.dumps(trend_data),
            total_species=len(today_data),
        ))

        # Set auth cookie if token in query string
        if request.args.get("token"):
            response.set_cookie(
                f"port_{slug}", request.args["token"],
                max_age=30 * 24 * 60 * 60,  # 30 days
                httponly=True, samesite="Lax",
            )

        return response

    @app.route("/port/<slug>/upload", methods=["GET", "POST"])
    def port_upload(slug: str):
        """Web form upload — fallback for ports that email photos/docs."""
        port = get_port(slug)
        if not port:
            return "Port not found", 404

        if request.method == "GET":
            return render_template("upload_form.html", port=port)

        # Handle form submission
        date = request.form.get("date", datetime.now().strftime("%Y-%m-%d"))

        # Check for file upload
        uploaded_file = request.files.get("file")
        if uploaded_file and uploaded_file.filename:
            # Save file and extract
            port_dir = UPLOAD_DIR / slug / date
            port_dir.mkdir(parents=True, exist_ok=True)
            file_path = port_dir / uploaded_file.filename
            uploaded_file.save(file_path)

            records = extract_from_file(file_path, port["name"], date)
            if records:
                upload_id = create_upload(
                    port_slug=slug, date=date,
                    method=f"web:{file_path.suffix.lstrip('.')}",
                    raw_file_path=str(file_path),
                    record_count=len(records),
                )
                upsert_prices_with_upload(records, upload_id)
                token = generate_confirm_token(upload_id)
                return redirect(url_for("confirm_upload_page", token=token))

            flash("Could not extract prices from that file. Please try a different format.")
            return redirect(url_for("port_upload", slug=slug))

        # Handle manual form entry
        records = _parse_form_prices(request.form, port["name"], date)
        if records:
            upload_id = create_upload(
                port_slug=slug, date=date, method="web:form",
                record_count=len(records),
            )
            upsert_prices_with_upload(records, upload_id)
            confirm_upload(upload_id, confirmed_by="web_form")
            flash(f"Published {len(records)} prices for {date}.")
            return redirect(url_for("port_dashboard", slug=slug))

        flash("No prices entered. Please fill in at least one row.")
        return redirect(url_for("port_upload", slug=slug))

    @app.route("/confirm/<token>")
    def confirm_upload_page(token: str):
        """Confirmation page — show extracted data for review."""
        upload_id = get_upload_for_token(token)
        if not upload_id:
            return "Invalid or expired confirmation link", 404

        upload = get_upload(upload_id)
        if not upload:
            return "Upload not found", 404

        port = get_port(upload["port_slug"])

        # Get the prices for this upload
        prices = get_prices_by_date(upload["date"], port["name"])

        return render_template(
            "confirm.html",
            upload=upload, port=port, prices=prices, token=token,
        )

    @app.route("/confirm/<token>/approve", methods=["POST"])
    def approve_upload(token: str):
        """Handle 'Looks good' confirmation."""
        upload_id = get_upload_for_token(token)
        if not upload_id:
            return "Invalid or expired confirmation link", 404

        confirm_upload(upload_id, confirmed_by=request.remote_addr)
        upload = get_upload(upload_id)
        port = get_port(upload["port_slug"]) if upload else None

        if port:
            return redirect(url_for("port_dashboard", slug=port["slug"]))
        return "Confirmed — thank you!", 200

    @app.route("/confirm/<token>/edit", methods=["GET", "POST"])
    def edit_upload(token: str):
        """Editable table for corrections."""
        upload_id = get_upload_for_token(token)
        if not upload_id:
            return "Invalid or expired confirmation link", 404

        upload = get_upload(upload_id)
        if not upload:
            return "Upload not found", 404

        port = get_port(upload["port_slug"])
        prices = get_prices_by_date(upload["date"], port["name"])

        if request.method == "GET":
            return render_template(
                "edit.html",
                upload=upload, port=port, prices=prices, token=token,
            )

        # Process corrections
        corrected_records = _parse_form_prices(request.form, port["name"], upload["date"])
        if corrected_records:
            # Log corrections by comparing to originals
            original_map = {
                (normalise_species(r[2]), r[3]): r for r in prices
            }
            for i, rec in enumerate(corrected_records):
                key = (normalise_species(rec.species), rec.grade)
                orig = original_map.get(key)
                if orig and orig[6] != rec.price_avg:
                    log_correction(
                        upload_id, "price_avg", i,
                        str(orig[6]), str(rec.price_avg),
                    )

            upsert_prices_with_upload(corrected_records, upload_id)
            confirm_upload(upload_id, confirmed_by="corrected")

        return redirect(url_for("port_dashboard", slug=port["slug"]))

    @app.route("/port/<slug>/template")
    def download_template(slug: str):
        """Download the port-specific XLSX upload template."""
        port = get_port(slug)
        if not port:
            return "Port not found", 404

        from quayside.template import generate_template

        path = generate_template(port["name"], port["code"])
        return send_file(
            path,
            as_attachment=True,
            download_name=f"quayside_prices_{port['code'].lower()}.xlsx",
        )

    return app


def _pct_in_range(value: float, min_val: float, max_val: float) -> int:
    """Calculate where a value sits in a range as a percentage (0-100)."""
    if max_val == min_val:
        return 50
    return max(0, min(100, round(((value - min_val) / (max_val - min_val)) * 100)))


def _build_trend_data(history: list[tuple]) -> dict:
    """Build trend data for chart.js from price history rows."""
    # Group by species, then by date
    from collections import defaultdict
    species_dates: dict[str, dict[str, float]] = defaultdict(dict)

    for date, species, _grade, _low, _high, avg in history:
        canonical = normalise_species(species)
        if avg and (date not in species_dates[canonical] or avg > species_dates[canonical][date]):
            species_dates[canonical][date] = avg

    # Get top 5 species by frequency
    species_freq = sorted(species_dates.keys(), key=lambda s: len(species_dates[s]), reverse=True)
    top_species = species_freq[:5]

    # Build chart data
    all_dates = sorted({d for sp in top_species for d in species_dates[sp]})

    return {
        "labels": all_dates,
        "datasets": [
            {
                "label": sp,
                "data": [species_dates[sp].get(d) for d in all_dates],
            }
            for sp in top_species
        ],
    }


def _parse_form_prices(form, port_name: str, date: str) -> list[PriceRecord]:
    """Parse price rows from a web form submission."""
    records = []
    now = datetime.now().isoformat()

    # Form sends species_0, grade_0, low_0, high_0, avg_0, etc.
    i = 0
    while f"species_{i}" in form:
        species = form.get(f"species_{i}", "").strip()
        if not species:
            i += 1
            continue

        grade = form.get(f"grade_{i}", "").strip()
        low = _form_float(form.get(f"low_{i}"))
        high = _form_float(form.get(f"high_{i}"))
        avg = _form_float(form.get(f"avg_{i}"))

        if avg is None and low is not None and high is not None:
            avg = round((low + high) / 2, 2)

        if avg is None and low is None and high is None:
            i += 1
            continue

        records.append(PriceRecord(
            date=date, port=port_name, species=species, grade=grade,
            price_low=low, price_high=high, price_avg=avg, scraped_at=now,
        ))
        i += 1

    return records


def _form_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    cleaned = val.strip().lstrip("£$€").strip()
    try:
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    app.run(debug=True, port=5000)
