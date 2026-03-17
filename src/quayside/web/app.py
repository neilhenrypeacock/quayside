"""Flask application — port dashboards, upload form, confirmation pages.

Run with: python -m quayside.web.app
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import jinja2
from flask import (
    Flask,
    flash,
    jsonify,
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
    get_latest_rich_date,
    get_latest_scraped_at,
    get_market_averages_for_date,
    get_market_averages_for_range,
    get_port,
    get_port_by_token,
    get_port_auction_dates,
    get_port_prices_history,
    get_prices_by_date,
    get_prices_for_date_range,
    get_same_day_last_week,
    get_species_availability_gaps,
    get_seasonal_comparison,
    get_upload,
    get_quality_issues,
    get_quality_summary,
    init_db,
    log_correction,
    seed_demo_data,
    seed_demo_port_data,
    upsert_prices_with_upload,
)
from quayside.extractors import extract_from_file
from quayside.review import build_monthly_data, build_weekly_data
from quayside.models import PriceRecord
from quayside.ports import seed_ports
from quayside.report import build_landing_data, build_report_data
from quayside.species import get_all_canonical_names, get_species_category, normalise_species

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
        seed_demo_port_data()

    @app.context_processor
    def inject_ticker():
        """Make ticker data available to all templates via base.html."""
        date = get_latest_rich_date()  # exclude sparse/demo-only dates
        if date:
            ld = build_landing_data(date)
            return {"_ticker_items": ld.get("ticker_items", []) if ld else []}
        return {"_ticker_items": []}

    @app.route("/")
    def landing():
        """Subscriber-focused marketing page."""
        date = get_latest_date()
        ld = build_landing_data(date) if date else None
        return render_template("landing.html", ld=ld)

    @app.route("/overview")
    def index():
        """Staging hub — links to all screens."""
        ports = get_all_ports(status="active")
        return render_template("index.html", ports=ports)

    @app.route("/for-ports")
    def for_ports():
        """Port-focused marketing and onboarding page."""
        return render_template("for_ports.html")

    @app.route("/digest")
    @app.route("/digest/<date>")
    def digest_page(date: str | None = None):
        """Web version of the daily email digest."""
        if date is None:
            date = get_latest_rich_date()
        if not date:
            return render_template("landing.html")  # No data yet

        data = build_report_data(date)
        digest_template = _digest_env.get_template("digest.html")
        digest_html = digest_template.render(**data)
        # Wrap in a simple page with nav
        return render_template("digest_wrapper.html", digest_html=digest_html, date=date)

    @app.route("/digest/weekly")
    @app.route("/digest/weekly/<date>")
    def weekly_digest(date: str | None = None):
        """Weekly review — 5-day snapshot with movers, benchmarks, spreads."""
        data = build_weekly_data(date)
        return render_template("weekly.html", data=data)

    @app.route("/digest/monthly")
    @app.route("/digest/monthly/<year_month>")
    def monthly_digest(year_month: str | None = None):
        """Monthly review — trends, volatility, reliability, availability."""
        data = build_monthly_data(year_month)
        return render_template("monthly.html", data=data)

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

        latest = get_latest_date() or datetime.now().strftime("%Y-%m-%d")
        # Allow ?date= param to view historical auctions
        date = request.args.get("date") or latest

        # Available auction dates for this port (for the date tab bar)
        available_dates = get_port_auction_dates(port["name"], limit=20)

        # Allow ?compare= param to override the comparison date; default = same weekday last week
        compare_date_param = request.args.get("compare")

        # Get this port's prices for today
        port_prices = get_prices_by_date(date, port["name"])

        # Get market averages for comparison
        market = get_market_averages_for_date(date)

        # Get comparison prices — either from ?compare= param or same-day last week
        if compare_date_param and compare_date_param != date:
            last_week_prices = {
                (r[2], r[3]): {"price_avg": r[6], "price_low": r[4], "price_high": r[5]}
                for r in get_prices_by_date(compare_date_param, port["name"])
            }
            compare_date = compare_date_param
        else:
            last_week_prices = get_same_day_last_week(port["name"], date)
            compare_date = None  # will be resolved to last same weekday label below

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
                vs_pct = round(((avg - market_avg) / market_avg) * 100, 1)
                position = {
                    "market_avg": round(market_avg, 2),
                    "market_min": round(market_min, 2),
                    "market_max": round(market_max, 2),
                    "port_count": market_info["port_count"],
                    "is_best": is_best,
                    "is_below": is_below,
                    "vs_pct": vs_pct,
                    "pct_of_range": _pct_in_range(avg, market_min, market_max),
                }

            # Same-day-last-week delta for this species/grade
            lw = last_week_prices.get((species, grade))
            vs_last_week = None
            if lw and lw["price_avg"] and avg:
                vs_last_week = round(
                    ((avg - lw["price_avg"]) / lw["price_avg"]) * 100, 1
                )

            today_data.append({
                "species": canonical,
                "raw_species": species,
                "grade": grade,
                "price_low": low,
                "price_high": high,
                "price_avg": avg,
                "position": position,
                "vs_last_week": vs_last_week,
                "category": get_species_category(canonical),
            })

        # Get 90-day history for trend chart (supports 7d/30d/90d toggles)
        history = get_port_prices_history(port["name"], days=90)
        trend_data = _build_trend_data(history)
        history_days = len({h[0] for h in history})  # distinct auction dates in history

        # Build best performers and insights
        best_performers = _build_best_performers(port["name"], date, days=30)
        all_insights = _build_insights(port["name"], date, today_data, history)

        # ── Grade mix: group rows by species for expandable view ──
        from collections import OrderedDict
        species_grades = OrderedDict()
        for item in today_data:
            sp = item["species"]
            if sp not in species_grades:
                species_grades[sp] = []
            species_grades[sp].append(item)

        # ── Hero summary stats ──
        avg_prices = [
            item["price_avg"] for item in today_data if item["price_avg"]
        ]
        hero_avg_price = round(
            sum(avg_prices) / len(avg_prices), 2
        ) if avg_prices else None

        # Count unique canonical species (not species×grade rows)
        hero_species_count = len(species_grades)

        # Count species (not grades) that beat the UK average
        above_count = sum(
            1 for items in species_grades.values()
            if items[0]["position"] and items[0]["position"]["vs_pct"] > 0
        )

        # Today vs same day last week (aggregate delta)
        hero_vs_last_week = None
        hero_last_week_price = None
        if last_week_prices:
            lw_avgs = [
                v["price_avg"] for v in last_week_prices.values()
                if v["price_avg"]
            ]
            if lw_avgs and avg_prices:
                lw_overall = sum(lw_avgs) / len(lw_avgs)
                today_overall = sum(avg_prices) / len(avg_prices)
                if lw_overall > 0:
                    hero_vs_last_week = round(
                        ((today_overall - lw_overall) / lw_overall) * 100, 1
                    )
                hero_last_week_price = round(lw_overall, 2)

        # Today vs UK market average (aggregate delta)
        # Only compare species this port actually sells — otherwise high-value species
        # traded only at other ports (turbot, lobster etc.) inflate the market avg unfairly.
        hero_vs_market = None
        port_canonical_species = {item["species"] for item in today_data}
        all_market_avgs = [
            info["avg"] for canon, info in market.items()
            if info.get("avg") and canon in port_canonical_species
        ]
        if all_market_avgs and avg_prices:
            market_overall = sum(all_market_avgs) / len(all_market_avgs)
            port_overall = sum(avg_prices) / len(avg_prices)
            if market_overall > 0:
                hero_vs_market = round(
                    ((port_overall - market_overall) / market_overall) * 100, 1
                )

        # ── Species availability gaps ──
        species_gaps = [
            normalise_species(s)
            for s in get_species_availability_gaps(port["name"], date)
        ]

        # ── Seasonal comparison ──
        seasonal_raw = get_seasonal_comparison(port["name"], date)
        seasonal_data = {
            normalise_species(sp): price
            for sp, price in seasonal_raw.items()
        }
        has_seasonal = bool(seasonal_data)

        # ── Day name for "vs last [day]" column header ──
        from datetime import datetime as dt
        try:
            _dt = dt.strptime(date, "%Y-%m-%d")
            day_name = _dt.strftime("%A")[:3]
            latest_date_display = _dt.strftime("%-d %b %Y")  # e.g. "16 Mar 2026"
        except ValueError:
            day_name = "Week"
            latest_date_display = date

        # ── Comparison date label for the prices table header ──
        if compare_date_param and compare_date_param != date:
            try:
                _cdt = dt.strptime(compare_date_param, "%Y-%m-%d")
                compare_label = _cdt.strftime("%-d %b")  # e.g. "9 Mar"
            except ValueError:
                compare_label = compare_date_param
            compare_date_display = compare_date_param
        else:
            compare_label = f"last {day_name}"
            compare_date_display = None

        # ── Data freshness: when was this date's data last scraped? ──
        scraped_at_raw = get_latest_scraped_at(port["name"], date)
        data_freshness = _format_data_freshness(scraped_at_raw, date)

        # ── Performance overview: week-over-week & month-over-month ──
        perf = _build_performance_overview(port["name"], date, history, market)

        # ── Per-category hero stats (for the category pill filter) ──
        category_stats = _build_category_stats(today_data, last_week_prices, market, history)

        response = app.make_response(render_template(
            "dashboard.html",
            port=port,
            date=date,
            data_freshness=data_freshness,
            today_data=today_data,
            trend_data=json.dumps(trend_data),
            history_days=history_days,
            total_species=hero_species_count,
            best_performers=best_performers,
            port_insights=all_insights["port"],
            market_insights=all_insights["market"],
            above_count=above_count,
            hero_avg_price=hero_avg_price,
            hero_vs_last_week=hero_vs_last_week,
            hero_last_week_price=hero_last_week_price,
            hero_vs_market=hero_vs_market,
            species_grades=species_grades,
            species_gaps=species_gaps,
            seasonal_data=seasonal_data,
            has_seasonal=has_seasonal,
            day_name=day_name,
            latest_date_display=latest_date_display,
            available_dates=available_dates,
            compare_label=compare_label,
            compare_date_display=compare_date_display,
            perf=perf,
            category_stats=json.dumps(category_stats),
        ))

        # Set auth cookie if token in query string
        if request.args.get("token"):
            response.set_cookie(
                f"port_{slug}", request.args["token"],
                max_age=30 * 24 * 60 * 60,  # 30 days
                httponly=True, samesite="Lax",
            )

        return response

    @app.route("/port/<slug>/prices")
    def port_prices_partial(slug: str):
        """Returns just the prices section HTML for AJAX date tab switching."""
        port = get_port(slug)
        if not port:
            return "Port not found", 404

        latest = get_latest_date() or datetime.now().strftime("%Y-%m-%d")
        date = request.args.get("date") or latest
        compare_date_param = request.args.get("compare")

        available_dates = get_port_auction_dates(port["name"], limit=20)
        port_prices = get_prices_by_date(date, port["name"])
        market = get_market_averages_for_date(date)

        if compare_date_param and compare_date_param != date:
            last_week_prices = {
                (r[2], r[3]): {"price_avg": r[6], "price_low": r[4], "price_high": r[5]}
                for r in get_prices_by_date(compare_date_param, port["name"])
            }
        else:
            last_week_prices = get_same_day_last_week(port["name"], date)
            compare_date_param = None

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
                is_below = avg < market_avg * 0.95
                vs_pct = round(((avg - market_avg) / market_avg) * 100, 1)
                position = {
                    "market_avg": round(market_avg, 2),
                    "market_min": round(market_min, 2),
                    "market_max": round(market_max, 2),
                    "port_count": market_info["port_count"],
                    "is_best": is_best,
                    "is_below": is_below,
                    "vs_pct": vs_pct,
                    "pct_of_range": _pct_in_range(avg, market_min, market_max),
                }

            lw = last_week_prices.get((species, grade))
            vs_last_week = None
            if lw and lw["price_avg"] and avg:
                vs_last_week = round(((avg - lw["price_avg"]) / lw["price_avg"]) * 100, 1)

            today_data.append({
                "species": canonical,
                "raw_species": species,
                "grade": grade,
                "price_low": low,
                "price_high": high,
                "price_avg": avg,
                "position": position,
                "vs_last_week": vs_last_week,
                "category": get_species_category(canonical),
            })

        from collections import OrderedDict
        species_grades = OrderedDict()
        for item in today_data:
            sp = item["species"]
            if sp not in species_grades:
                species_grades[sp] = []
            species_grades[sp].append(item)

        seasonal_raw = get_seasonal_comparison(port["name"], date)
        seasonal_data = {
            normalise_species(sp): price for sp, price in seasonal_raw.items()
        }
        has_seasonal = bool(seasonal_data)

        from datetime import datetime as dt
        try:
            _dt = dt.strptime(date, "%Y-%m-%d")
            day_name = _dt.strftime("%A")[:3]
            latest_date_display = _dt.strftime("%-d %b %Y")
        except ValueError:
            day_name = "Week"
            latest_date_display = date

        if compare_date_param and compare_date_param != date:
            try:
                _cdt = dt.strptime(compare_date_param, "%Y-%m-%d")
                compare_label = _cdt.strftime("%-d %b")
            except ValueError:
                compare_label = compare_date_param
            compare_date_display = compare_date_param
        else:
            compare_label = f"last {day_name}"
            compare_date_display = None

        return render_template(
            "prices_partial.html",
            port=port,
            date=date,
            latest_date_display=latest_date_display,
            available_dates=available_dates,
            day_name=day_name,
            compare_label=compare_label,
            compare_date_display=compare_date_display,
            species_grades=species_grades,
            has_seasonal=has_seasonal,
            seasonal_data=seasonal_data,
        )

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

    @app.route("/ops")
    def ops_dashboard():
        """Internal ops dashboard — scraper health, port status, data coverage."""
        from collections import defaultdict, OrderedDict
        from datetime import datetime as dt, timedelta

        conn = __import__("quayside.db", fromlist=["get_connection"]).get_connection()

        # All ports
        conn.row_factory = sqlite3.Row
        all_ports = [dict(r) for r in conn.execute("SELECT * FROM ports ORDER BY region, name").fetchall()]

        # Group ports by region — geographic order (north to south)
        _REGION_ORDER = [
            "Scotland — North & Islands",
            "Scotland — North East",
            "Scotland — South East",
            "England — North East",
            "England — North West",
            "England — East",
            "England — South West",
            "Wales",
            "Northern Ireland",
        ]
        _region_rank = {r: i for i, r in enumerate(_REGION_ORDER)}

        # Split into live vs pipeline (exclude Demo Port from ops display)
        live_ports = [p for p in all_ports if p["status"] == "active" and p["name"] != "Demo Port"]
        pipeline_ports = [p for p in all_ports if p["status"] in ("outreach", "future")]
        # Pipeline: outreach first, then future — Scotland before England within each
        _status_rank = {"outreach": 0, "future": 1}
        pipeline_ports.sort(key=lambda p: (
            _status_rank.get(p["status"], 99),
            _region_rank.get(p["region"], 99),
            p["name"],
        ))

        # Build region-grouped dict for live ports only
        live_by_region: dict[str, list[dict]] = OrderedDict()
        for p in sorted(live_ports, key=lambda p: (_region_rank.get(p["region"], 99), p["name"])):
            live_by_region.setdefault(p["region"], []).append(p)

        # Keep full region grouping for other uses
        ports_by_region: dict[str, list[dict]] = OrderedDict()
        for p in sorted(all_ports, key=lambda p: (_region_rank.get(p["region"], 99), p["name"])):
            ports_by_region.setdefault(p["region"], []).append(p)

        # Last 21 days of price data per port (3 full weeks)
        daily_data = conn.execute(
            """SELECT date, port, COUNT(DISTINCT species) as species_count,
                      COUNT(*) as record_count, MIN(scraped_at) as first_scraped
               FROM prices
               WHERE date >= date('now', '-21 days')
               GROUP BY date, port
               ORDER BY date DESC, port"""
        ).fetchall()

        # Build per-port coverage map: {port: {date: {species, records, scraped_at}}}
        port_coverage: dict[str, dict[str, dict]] = defaultdict(dict)
        for row in daily_data:
            port_coverage[row["port"]][row["date"]] = {
                "species": row["species_count"],
                "records": row["record_count"],
                "scraped_at": row["first_scraped"],
            }

        # Compute per-port data publishing times from scraped_at timestamps
        port_data_timing: dict[str, dict] = {}
        for _pt_port, _pt_date_map in port_coverage.items():
            _pt_minutes: list[int] = []
            for _pt_info in _pt_date_map.values():
                _raw = _pt_info.get("scraped_at")
                if not _raw:
                    continue
                try:
                    _ts = dt.fromisoformat(_raw)
                    _pt_minutes.append(_ts.hour * 60 + _ts.minute)
                except Exception:
                    pass
            if len(_pt_minutes) >= 3:
                _pt_minutes.sort()
                _mid = len(_pt_minutes) // 2
                port_data_timing[_pt_port] = {
                    "median": f"{_pt_minutes[_mid] // 60:02d}:{_pt_minutes[_mid] % 60:02d}",
                    "earliest": f"{min(_pt_minutes) // 60:02d}:{min(_pt_minutes) % 60:02d}",
                    "latest": f"{max(_pt_minutes) // 60:02d}:{max(_pt_minutes) % 60:02d}",
                    "sample_days": len(_pt_minutes),
                }

        # Build week-structured dates: current week (Mon-Sun) + 2 previous weeks
        today = dt.now()
        # Find Monday of current week
        current_monday = today - timedelta(days=today.weekday())
        weeks = []  # list of {label, dates: [{date_str, dow_name, is_today, is_weekend}]}
        for week_offset in range(3):
            monday = current_monday - timedelta(weeks=week_offset)
            week_dates = []
            for day_offset in range(7):
                d = monday + timedelta(days=day_offset)
                if d > today:
                    continue  # don't show future dates
                week_dates.append({
                    "date_str": d.strftime("%Y-%m-%d"),
                    "dow_name": d.strftime("%a"),
                    "day_num": d.strftime("%d"),
                    "is_today": d.date() == today.date(),
                    "is_weekend": d.weekday() >= 5,
                })
            if week_dates:
                label = f"w/c {monday.strftime('%d %b')}"
                weeks.append({"label": label, "dates": week_dates})

        # Flat list of all dates for coverage (newest first)
        all_coverage_dates = []
        for week in weeks:
            for dd in week["dates"]:
                all_coverage_dates.append(dd["date_str"])

        # Unique species per port (all time)
        species_per_port = {}
        for row in conn.execute(
            """SELECT port, COUNT(DISTINCT species) as species_count
               FROM prices GROUP BY port"""
        ).fetchall():
            species_per_port[row["port"]] = row["species_count"]

        # First data date per port
        first_data_per_port = {}
        for row in conn.execute(
            "SELECT port, MIN(date) as first_date FROM prices GROUP BY port"
        ).fetchall():
            first_data_per_port[row["port"]] = row["first_date"]

        # Success days per port (distinct dates with data)
        success_days_per_port = {}
        for row in conn.execute(
            "SELECT port, COUNT(DISTINCT date) as success_days FROM prices GROUP BY port"
        ).fetchall():
            success_days_per_port[row["port"]] = row["success_days"]

        # Fails per port: weekdays since first data minus success days
        from datetime import date as _date
        today_date = today.date()
        fails_per_port = {}
        for port_name, first_date_str in first_data_per_port.items():
            start = _date.fromisoformat(first_date_str)
            weekday_count = 0
            d_iter = start
            while d_iter <= today_date:
                if d_iter.weekday() < 5:
                    weekday_count += 1
                d_iter += timedelta(days=1)
            fails_per_port[port_name] = max(0, weekday_count - success_days_per_port.get(port_name, 0))

        # Price records per port (total count, used in Live Ports table)
        port_records = {}
        for row in conn.execute(
            "SELECT port, COUNT(*) as record_count FROM prices GROUP BY port"
        ).fetchall():
            port_records[row["port"]] = row["record_count"]

        # 30-day rolling port value: SUM(weight_kg * price_avg) for ports that publish weight
        port_value_30d = {}
        for row in conn.execute(
            """SELECT port, SUM(weight_kg * price_avg) as total_value
               FROM prices
               WHERE date >= date('now', '-30 days')
                 AND weight_kg IS NOT NULL AND weight_kg > 0
                 AND price_avg IS NOT NULL
               GROUP BY port"""
        ).fetchall():
            if row["total_value"]:
                port_value_30d[row["port"]] = row["total_value"]

        # Total records
        totals = conn.execute(
            "SELECT COUNT(*) as total, COUNT(DISTINCT date) as dates FROM prices"
        ).fetchone()

        # Active scraper ports (excludes Demo Port — its seeded data would mask real scrape gaps)
        active_port_names = [p["name"] for p in all_ports if p["status"] == "active" and p["name"] != "Demo Port"]

        # --- Scrape Alerts: detect empty/missing scrapes for current + last week ---
        # Expected auction days per port (based on known schedules)
        expected_auction_days = {
            "Peterhead": {0, 1, 2, 3, 4},    # Mon-Fri
            "Brixham": {0, 1, 2, 3, 4},       # Mon-Fri
            "Newlyn": {0, 1, 2, 3, 4},         # Mon-Fri
            "Scrabster": {0, 1, 2, 3, 4},      # Mon-Fri
            "Lerwick": {0, 1, 2, 3, 4},         # Mon-Fri (variable landings)
        }

        scrape_alerts = []
        # Check current week + last week (only past dates)
        check_start = current_monday - timedelta(weeks=1)
        d = check_start
        while d <= today:
            date_str = d.strftime("%Y-%m-%d")
            dow = d.weekday()
            is_today = d.date() == today.date()

            for port_name in active_port_names:
                expected_days = expected_auction_days.get(port_name, {0, 1, 2, 3, 4})
                has_data = date_str in port_coverage.get(port_name, {})

                if dow >= 5:
                    continue  # skip weekends — no auctions expected

                if not has_data and dow in expected_days:
                    # Skip dates before this port started scraping — not a gap
                    if date_str < first_data_per_port.get(port_name, "0000-00-00"):
                        continue
                    # Determine reason
                    if is_today:
                        # Check if any port has data today
                        any_port_today = any(
                            date_str in port_coverage.get(pn, {})
                            for pn in active_port_names
                        )
                        if any_port_today:
                            reason = "Scrape returned empty"
                        else:
                            reason = "Not yet scraped today"
                    else:
                        # Past weekday with no data
                        any_port_that_day = any(
                            date_str in port_coverage.get(pn, {})
                            for pn in active_port_names
                        )
                        if not any_port_that_day:
                            reason = "Public holiday — no auctions"
                        else:
                            reason = "No data published"
                    scrape_alerts.append({
                        "port": port_name,
                        "date": date_str,
                        "dow": d.strftime("%a"),
                        "reason": reason,
                        "is_today": is_today,
                    })
            d += timedelta(days=1)

        # Sort alerts: today first, then most recent
        scrape_alerts.sort(key=lambda a: (not a["is_today"], a["date"]), reverse=False)
        scrape_alerts.sort(key=lambda a: a["date"], reverse=True)

        # Auction frequency analysis: which days of the week does each port have data?
        dow_data = conn.execute(
            """SELECT port,
                      CASE CAST(strftime('%w', date) AS INTEGER)
                        WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
                        WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri'
                        WHEN 6 THEN 'Sat' END as dow,
                      COUNT(DISTINCT date) as count
               FROM prices
               WHERE date >= date('now', '-90 days')
               GROUP BY port, strftime('%w', date)
               ORDER BY port, strftime('%w', date)"""
        ).fetchall()

        # Build frequency map: {port: {dow: count}}
        port_frequency: dict[str, dict[str, int]] = defaultdict(dict)
        for row in dow_data:
            port_frequency[row["port"]][row["dow"]] = row["count"]

        # Known auction schedules for display
        known_schedules = {
            "Peterhead": "Mon–Fri, morning auction via SWFPA",
            "Brixham": "Mon–Fri, electronic auction",
            "Newlyn": "Mon–Fri, morning market",
            "Scrabster": "Mon–Fri, consignment sales",
            "Lerwick": "Mon–Fri, varies with landings",
        }

        # Classify frequency
        def classify_frequency(dow_counts: dict[str, int]) -> str:
            active_days = [d for d, c in dow_counts.items() if c >= 3]
            if len(active_days) >= 4:
                return "Daily (Mon–Fri)"
            elif len(active_days) == 3:
                return f"3×/week ({', '.join(sorted(active_days))})"
            elif len(active_days) == 2:
                return f"2×/week ({', '.join(sorted(active_days))})"
            elif len(active_days) == 1:
                return f"Weekly ({active_days[0]})"
            return "Irregular"

        # Data gaps for the gap section (last 10 weekdays)
        gaps = []
        weekdays_checked = 0
        d = today
        while weekdays_checked < 10:
            if d.weekday() < 5:
                date_str = d.strftime("%Y-%m-%d")
                for port_name in active_port_names:
                    if date_str not in port_coverage.get(port_name, {}):
                        gaps.append({"port": port_name, "date": date_str, "type": "missing"})
                weekdays_checked += 1
            d -= timedelta(days=1)

        # Upload stats
        upload_stats = conn.execute(
            """SELECT status, COUNT(*) as count FROM uploads GROUP BY status"""
        ).fetchall()
        upload_summary = {row["status"]: row["count"] for row in upload_stats}

        # Correction count
        correction_count = conn.execute(
            "SELECT COUNT(*) FROM extraction_corrections"
        ).fetchone()[0]

        # --- Scrape log: last 7 days of attempts per port ---
        scrape_log_rows = []
        try:
            scrape_log_rows = conn.execute(
                """SELECT port, ran_at, success, record_count, error_type, error_msg
                   FROM scrape_log
                   WHERE ran_at >= datetime('now', '-7 days')
                   ORDER BY ran_at DESC"""
            ).fetchall()
        except Exception:
            pass

        # Last successful scrape date/day per port (from scrape_log, fallback to prices.scraped_at)
        last_scrape_info: dict[str, dict] = {}
        for row in scrape_log_rows:
            port_name = row["port"]
            if row["success"] and port_name not in last_scrape_info:
                ran_at_str = row["ran_at"]
                try:
                    from datetime import datetime as _dt2
                    ts = _dt2.fromisoformat(ran_at_str)
                    last_scrape_info[port_name] = {
                        "date": ts.strftime("%Y-%m-%d"),
                        "day": ts.strftime("%a"),
                    }
                except Exception:
                    pass

        # Fallback: use MAX(scraped_at) from prices for ports not yet in scrape_log
        fallback_rows = conn.execute(
            "SELECT port, MAX(scraped_at) as last_scraped FROM prices GROUP BY port"
        ).fetchall()
        for row in fallback_rows:
            if row["port"] not in last_scrape_info and row["last_scraped"]:
                try:
                    from datetime import datetime as _dt3
                    ts = _dt3.fromisoformat(row["last_scraped"])
                    last_scrape_info[row["port"]] = {
                        "date": ts.strftime("%Y-%m-%d"),
                        "day": ts.strftime("%a"),
                    }
                except Exception:
                    pass

        # Today's intraday scrape timeline per port: 30-min slots 07:00–17:00
        today_str_for_log = today.strftime("%Y-%m-%d")
        _SCRAPE_SLOTS = [f"{h:02d}:{m:02d}" for h in range(7, 17) for m in (0, 30)]
        # Build: {port: {slot: {"attempted": bool, "success": bool}}}
        today_timeline: dict[str, dict[str, dict]] = {}
        for row in scrape_log_rows:
            if not row["ran_at"].startswith(today_str_for_log):
                continue
            port_name = row["port"]
            try:
                from datetime import datetime as _dt4
                ts = _dt4.fromisoformat(row["ran_at"])
                # Round down to nearest 30-min slot
                slot_min = 0 if ts.minute < 30 else 30
                slot = f"{ts.hour:02d}:{slot_min:02d}"
                if port_name not in today_timeline:
                    today_timeline[port_name] = {}
                # Keep last result for the slot (most recent wins)
                today_timeline[port_name][slot] = {
                    "attempted": True,
                    "success": bool(row["success"]),
                    "record_count": row["record_count"],
                    "error_type": row["error_type"],
                }
            except Exception:
                pass

        # Today's scrape summary: per-port first attempt time, success time, record count
        today_scrape_summary: dict[str, dict] = {}
        for row in reversed(scrape_log_rows):  # reversed = chronological (earliest first)
            if not row["ran_at"].startswith(today_str_for_log):
                continue
            port_name = row["port"]
            try:
                from datetime import datetime as _dt5
                ts = _dt5.fromisoformat(row["ran_at"])
                time_str = ts.strftime("%H:%M")
                if port_name not in today_scrape_summary:
                    today_scrape_summary[port_name] = {
                        "first_attempt": time_str,
                        "last_success": None,
                        "status": "failed",
                        "record_count": 0,
                        "error_type": None,
                    }
                if row["success"]:
                    today_scrape_summary[port_name]["last_success"] = time_str
                    today_scrape_summary[port_name]["status"] = "success"
                    today_scrape_summary[port_name]["record_count"] = row["record_count"]
                elif today_scrape_summary[port_name]["status"] != "success":
                    today_scrape_summary[port_name]["error_type"] = row["error_type"]
            except Exception:
                pass

        # Detect stale scrapes: ran today and returned records, but data date is not today
        latest_data_date_rows = conn.execute(
            "SELECT port, MAX(date) as last_data_date FROM prices GROUP BY port"
        ).fetchall()
        latest_data_date = {row["port"]: row["last_data_date"] for row in latest_data_date_rows}

        conn.close()

        today_str = today.strftime("%Y-%m-%d")
        today_is_weekday = today.weekday() < 5

        # Mark stale: scraper ran and "succeeded" but the newest data in DB is not today
        for port_name, summary in today_scrape_summary.items():
            if summary["status"] == "success":
                last_date = latest_data_date.get(port_name)
                if last_date and last_date < today_str:
                    from datetime import datetime as _dt6
                    summary["status"] = "stale"
                    summary["last_data_date"] = last_date
                    summary["last_data_date_display"] = _dt6.strptime(last_date, "%Y-%m-%d").strftime("%-d %b")

        # Summary counts for the pipeline banner
        today_succeeded = [p for p in today_scrape_summary.values() if p["status"] == "success"]
        today_failed = [p for p in today_scrape_summary.values() if p["status"] != "success"]
        today_attempted_count = len(today_scrape_summary)
        today_succeeded_count = len(today_succeeded)
        # First run time (earliest first_attempt across all ports)
        all_attempt_times = [v["first_attempt"] for v in today_scrape_summary.values() if v.get("first_attempt")]
        today_first_run = min(all_attempt_times) if all_attempt_times else None
        # Next scheduled check time (next 10-min boundary within 07:00–17:00 UTC)
        _now = today
        next_scrape_str: str | None = None
        if 7 <= _now.hour < 17:
            _next_min = ((_now.minute // 10) + 1) * 10
            _next_hour = _now.hour
            if _next_min >= 60:
                _next_min = 0
                _next_hour += 1
            if _next_hour < 17:
                next_scrape_str = f"{_next_hour:02d}:{_next_min:02d}"
        # Separate today's alerts from historical gaps
        today_alerts = [a for a in scrape_alerts if a["is_today"]]
        historical_alerts = [a for a in scrape_alerts if not a["is_today"]]

        # Data quality
        quality_issues = get_quality_issues(days=7)
        quality_summary = get_quality_summary()

        return render_template(
            "ops.html",
            ports=all_ports,
            ports_by_region=ports_by_region,
            live_ports=live_ports,
            live_by_region=live_by_region,
            pipeline_ports=pipeline_ports,
            port_coverage=dict(port_coverage),
            weeks=weeks,
            species_per_port=species_per_port,
            total_records=totals["total"],
            total_dates=totals["dates"],
            active_port_names=active_port_names,
            port_frequency=dict(port_frequency),
            known_schedules=known_schedules,
            classify_frequency=classify_frequency,
            scrape_alerts=scrape_alerts,
            gaps=gaps[:20],
            upload_summary=upload_summary,
            correction_count=correction_count,
            first_data_per_port=first_data_per_port,
            success_days_per_port=success_days_per_port,
            fails_per_port=fails_per_port,
            port_records=port_records,
            port_value_30d=port_value_30d,
            last_scrape_info=last_scrape_info,
            today_timeline=today_timeline,
            scrape_slots=_SCRAPE_SLOTS,
            today_str=today_str,
            today_is_weekday=today_is_weekday,
            today_scrape_summary=today_scrape_summary,
            today_attempted_count=today_attempted_count,
            today_succeeded_count=today_succeeded_count,
            today_first_run=today_first_run,
            next_scrape_str=next_scrape_str,
            today_alerts=today_alerts,
            historical_alerts=historical_alerts,
            quality_issues=quality_issues,
            quality_summary=quality_summary,
        )

    @app.route("/ops/run-quality-check", methods=["POST"])
    def ops_run_quality_check():
        """Run quality checks now and return JSON summary."""
        from quayside.quality import run_quality_checks
        summary = run_quality_checks()
        return jsonify({"ok": True, "errors": summary["errors"], "warns": summary["warns"]})

    @app.route("/ops/quality-report")
    def ops_quality_report():
        """Comprehensive quality report — port dashboards, digest preview, ops health."""
        from datetime import date as _date_type
        from quayside.quality import build_comprehensive_report
        date_param = request.args.get("date") or _date_type.today().isoformat()
        report = build_comprehensive_report(date_param)
        return render_template("quality_report.html", report=report, date=date_param)

    @app.route("/port/<slug>/export")
    def export_port_data(slug: str):
        """Download all price data for this port as CSV."""
        import csv
        import io

        port = get_port(slug)
        if not port:
            return "Port not found", 404

        history = get_port_prices_history(port["name"], days=365)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Species", "Grade", "Price Low", "Price High", "Price Avg"])
        for date, species, grade, low, high, avg in history:
            writer.writerow([date, species, grade, low, high, avg])

        from flask import Response
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=quayside_{slug}_prices.csv",
            },
        )

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

    # ── Submit form ──

    @app.route("/port/submit")
    @app.route("/port/<slug>/submit")
    def port_submit(slug: str | None = None):
        """Price submission form — no login required."""
        ports = get_all_ports(status="active")
        today = datetime.now().strftime("%Y-%m-%d")
        species_list = get_all_canonical_names()
        selected_port = None
        if slug:
            port = get_port(slug)
            if port:
                selected_port = port["name"]
        return render_template(
            "submit.html", ports=ports, today=today,
            species_list=species_list, selected_port=selected_port,
            port_slug=slug,
        )

    # ── Ingest API ──

    @app.route("/api/v1/ingest", methods=["POST"])
    def api_ingest():
        """Accept manual price submissions as JSON.

        Payload: {port, date, rows: [{species, grade, price_avg, notes?}], overwrite?}
        """
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON payload."}), 400

        port_name = (data.get("port") or "").strip()
        date = (data.get("date") or "").strip()
        rows = data.get("rows") or []
        overwrite = bool(data.get("overwrite", False))

        # Validate required fields
        if not port_name:
            return jsonify({"error": "port is required."}), 400
        if not date:
            return jsonify({"error": "date is required."}), 400
        if not rows:
            return jsonify({"error": "At least one price row is required."}), 400

        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD format."}), 400

        # Validate port exists
        all_port_names = {p["name"] for p in get_all_ports()}
        if port_name not in all_port_names:
            return jsonify({"error": f"Unknown port: {port_name}"}), 400

        # Check for duplicates unless overwrite
        if not overwrite:
            existing = get_prices_by_date(date, port_name)
            if existing:
                return jsonify({
                    "error": f"Data already exists for {port_name} on {date} ({len(existing)} rows).",
                }), 409

        # Build PriceRecord list
        now = datetime.now().isoformat()
        records = []
        errors = []
        for i, row in enumerate(rows):
            species = (row.get("species") or "").strip()
            if not species:
                errors.append(f"Row {i + 1}: species is required.")
                continue
            species_lower = species.lower()

            grade = (row.get("grade") or "").strip()
            price_avg = row.get("price_avg")

            if price_avg is None:
                errors.append(f"Row {i + 1}: price_avg is required.")
                continue
            try:
                price_avg = round(float(price_avg), 2)
            except (ValueError, TypeError):
                errors.append(f"Row {i + 1}: price_avg must be a number.")
                continue
            if price_avg <= 0:
                errors.append(f"Row {i + 1}: price_avg must be positive.")
                continue

            records.append(PriceRecord(
                date=date,
                port=port_name,
                species=species_lower,
                grade=grade,
                price_low=None,
                price_high=None,
                price_avg=price_avg,
                scraped_at=now,
            ))

        if errors:
            return jsonify({"error": "Validation failed.", "details": errors}), 400

        if not records:
            return jsonify({"error": "No valid rows to insert."}), 400

        # Write in a single transaction
        from quayside.db import get_connection
        conn = get_connection()
        try:
            conn.executemany(
                """INSERT OR REPLACE INTO prices
                   (date, port, species, grade, price_low, price_high, price_avg, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (r.date, r.port, r.species, r.grade,
                     r.price_low, r.price_high, r.price_avg, r.scraped_at)
                    for r in records
                ],
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.exception("Ingest transaction failed")
            return jsonify({"error": "Database error.", "details": str(e)}), 500
        finally:
            conn.close()

        return jsonify({
            "message": f"Submitted {len(records)} prices for {port_name} on {date}.",
            "count": len(records),
            "port": port_name,
            "date": date,
        }), 201

    # ── CSV Export API ──

    @app.route("/api/v1/export/csv")
    def api_export_csv():
        """Export filtered price data as CSV download.

        Query params: port (required), date_from, date_to, species, grade.
        """
        import csv
        import io

        port_name = request.args.get("port", "").strip()
        if not port_name:
            return jsonify({"error": "port query parameter is required."}), 400

        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        species_filter = request.args.get("species", "").strip().lower()
        grade_filter = request.args.get("grade", "").strip()

        # Default date range: last 30 days
        if not date_to:
            date_to = datetime.now().strftime("%Y-%m-%d")
        if not date_from:
            from datetime import timedelta
            date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # Query prices
        from quayside.db import get_connection
        conn = get_connection()
        query = """SELECT date, port, species, grade, price_low, price_high, price_avg
                   FROM prices
                   WHERE port = ? AND date >= ? AND date <= ?"""
        params: list = [port_name, date_from, date_to]

        if species_filter:
            query += " AND LOWER(species) = ?"
            params.append(species_filter)
        if grade_filter:
            query += " AND grade = ?"
            params.append(grade_filter)

        query += " ORDER BY date DESC, species, grade"
        rows = conn.execute(query, params).fetchall()
        conn.close()

        # Build CSV
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Port", "Species", "Grade", "Price Low", "Price High", "Price Avg"])
        for row in rows:
            writer.writerow(row)

        # Build filename
        safe_port = port_name.lower().replace(" ", "_")
        filename = f"quayside_{safe_port}_{date_from}_{date_to}.csv"

        from flask import Response
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # ── Trade dashboard routes ────────────────────────────────────────────────

    TRADE_TOKEN = os.environ.get("QUAYSIDE_TRADE_TOKEN", "")

    def _check_trade_access() -> bool:
        """Return True if the request has a valid trade access token/cookie."""
        if not TRADE_TOKEN:
            return True  # No token set — open in dev mode
        token = request.args.get("token") or request.cookies.get("trade_access")
        return token == TRADE_TOKEN

    @app.route("/trade")
    @app.route("/trade/<date>")
    def trade_dashboard(date: str | None = None):
        from quayside.trade import build_trade_data

        if not _check_trade_access():
            return render_template("trade_gate.html"), 403

        if date is None:
            date = get_latest_rich_date()
        if not date:
            return "No data available", 404

        data = build_trade_data(date)

        response = app.make_response(render_template("trade.html", **data))

        # Set access cookie if valid token was passed in URL (30-day expiry)
        if TRADE_TOKEN:
            url_token = request.args.get("token")
            if url_token == TRADE_TOKEN:
                response.set_cookie(
                    "trade_access",
                    url_token,
                    max_age=30 * 24 * 60 * 60,
                    httponly=True,
                    samesite="Lax",
                )
        return response

    @app.route("/trade/export")
    def trade_export():
        """Download filtered price data as CSV."""
        import csv
        import io

        from flask import Response

        from quayside.db import get_prices_for_date_range
        from quayside.species import normalise_species

        if not _check_trade_access():
            return "Access denied", 403

        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        species_filter = request.args.get("species", "").strip().lower()

        if not date_to:
            date_to = datetime.now().strftime("%Y-%m-%d")
        if not date_from:
            from datetime import timedelta
            date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        rows = get_prices_for_date_range(date_from, date_to)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Port", "Raw Species", "Canonical Species",
                         "Grade", "Price Low", "Price High", "Price Avg"])
        for date_val, port, species, grade, low, high, avg in rows:
            canonical = normalise_species(species)
            if species_filter and canonical.lower() != species_filter:
                continue
            writer.writerow([date_val, port, species, canonical, grade,
                             f"{low:.2f}" if low is not None else "",
                             f"{high:.2f}" if high is not None else "",
                             f"{avg:.2f}" if avg is not None else ""])

        filename = f"quayside_trade_{date_from}_{date_to}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    from quayside.scheduler import start_scheduler
    start_scheduler(app)

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


def _build_best_performers(
    port_name: str, date: str, days: int = 30,
) -> dict:
    """Build strongest species and best days data for a port."""
    from collections import defaultdict
    from datetime import datetime as dt, timedelta

    end_date = date
    start_date = (dt.strptime(date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")

    # Get this port's history
    port_history = get_port_prices_history(port_name, days=days)
    # Get market averages for the same range
    market_range = get_market_averages_for_range(start_date, end_date)

    # Group port prices by (date, species) → best avg
    port_by_date_species: dict[str, dict[str, float]] = defaultdict(dict)
    for hist_date, species, _grade, _low, _high, avg in port_history:
        if avg:
            canonical = normalise_species(species)
            if canonical not in port_by_date_species[hist_date] or avg > port_by_date_species[hist_date][canonical]:
                port_by_date_species[hist_date][canonical] = avg

    # --- Strongest species: % above market average over period ---
    species_vs_market: dict[str, list[float]] = defaultdict(list)
    species_above_count: dict[str, int] = defaultdict(int)
    species_total_days: dict[str, int] = defaultdict(int)
    species_avg_price: dict[str, list[float]] = defaultdict(list)

    for hist_date, species_prices in port_by_date_species.items():
        market_day = market_range.get(hist_date, {})
        for species, price in species_prices.items():
            raw_market = market_day.get(species)
            if raw_market and raw_market > 0:
                vs_pct = ((price - raw_market) / raw_market) * 100
                species_vs_market[species].append(vs_pct)
                species_total_days[species] += 1
                if vs_pct > 0:
                    species_above_count[species] += 1
            species_avg_price[species].append(price)

    strongest = []
    for species, vs_list in species_vs_market.items():
        avg_vs = sum(vs_list) / len(vs_list)
        avg_price = sum(species_avg_price[species]) / len(species_avg_price[species])
        total_days = species_total_days[species]
        above_days = species_above_count[species]
        strongest.append({
            "species": species,
            "avg_price": round(avg_price, 2),
            "vs_market_pct": round(avg_vs, 1),
            "above_days": above_days,
            "total_days": total_days,
        })
    strongest.sort(key=lambda x: x["vs_market_pct"], reverse=True)

    # --- Month summary: holistic top-line view ---
    trading_dates = sorted(port_by_date_species.keys())
    total_sessions = len(trading_dates)

    # Per-day stats: avg price and species count
    day_stats = []
    all_month_prices = []
    for d in trading_dates:
        prices = list(port_by_date_species[d].values())
        day_avg = sum(prices) / len(prices) if prices else 0
        day_stats.append({
            "date": d,
            "avg_price": round(day_avg, 2),
            "species_count": len(prices),
        })
        all_month_prices.extend(prices)

    month_avg = round(
        sum(all_month_prices) / len(all_month_prices), 2,
    ) if all_month_prices else 0

    # First half vs second half trend
    month_trend_pct = None
    if len(day_stats) >= 4:
        mid = len(day_stats) // 2
        first_half = [p for ds in day_stats[:mid] for p in port_by_date_species[ds["date"]].values()]
        second_half = [p for ds in day_stats[mid:] for p in port_by_date_species[ds["date"]].values()]
        if first_half and second_half:
            fh_avg = sum(first_half) / len(first_half)
            sh_avg = sum(second_half) / len(second_half)
            if fh_avg > 0:
                month_trend_pct = round(((sh_avg - fh_avg) / fh_avg) * 100, 1)

    # Busiest and quietest days
    busiest = max(day_stats, key=lambda x: x["species_count"]) if day_stats else None
    quietest = min(day_stats, key=lambda x: x["species_count"]) if day_stats else None

    # Highest and lowest avg price days
    best_price_day = max(day_stats, key=lambda x: x["avg_price"]) if day_stats else None
    worst_price_day = min(day_stats, key=lambda x: x["avg_price"]) if day_stats else None

    # Unique species this month
    all_month_species = set()
    for d_prices in port_by_date_species.values():
        all_month_species.update(d_prices.keys())

    month_summary = {
        "total_sessions": total_sessions,
        "month_avg": month_avg,
        "month_trend_pct": month_trend_pct,
        "total_species": len(all_month_species),
        "busiest_day": busiest,
        "quietest_day": quietest,
        "best_price_day": best_price_day,
        "worst_price_day": worst_price_day,
    }

    return {
        "strongest_species": strongest[:5],
        "month_summary": month_summary,
    }


def _build_insights(
    port_name: str, date: str, today_data: list[dict],
    history: list[tuple],
) -> dict:
    """Generate rule-based insights split into port-specific and market-wide.

    Returns {"port": [...], "market": [...]}.
    """
    from collections import defaultdict
    from datetime import datetime as dt, timedelta

    port_insights = []
    market_insights = []

    # Get market averages for today
    market = get_market_averages_for_date(date)

    # Each insight gets a priority (lower = more important) for ranking
    _ranked_port: list[tuple[int, dict]] = []
    _ranked_market: list[tuple[int, dict]] = []

    recent_dates = sorted({h[0] for h in history}, reverse=True)

    # ═══ PORT INTELLIGENCE — historical performance patterns ═══

    # --- Day-of-week pattern ---
    dow_prices: dict[int, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            try:
                dow = dt.strptime(hist_date, "%Y-%m-%d").weekday()
                dow_prices[dow].append(avg)
            except ValueError:
                pass

    if dow_prices:
        dow_avgs = {
            dow: sum(prices) / len(prices)
            for dow, prices in dow_prices.items()
        }
        best_dow = max(dow_avgs, key=dow_avgs.get)
        best_dow_avg = dow_avgs[best_dow]
        other_avg = sum(
            v for k, v in dow_avgs.items() if k != best_dow
        ) / max(1, len(dow_avgs) - 1)
        if other_avg > 0 and ((best_dow_avg - other_avg) / other_avg) > 0.02:
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
            if best_dow < 5:
                pct_diff = round(((best_dow_avg - other_avg) / other_avg) * 100, 1)
                _ranked_port.append((1, {
                    "category": "PATTERN",
                    "text": f"{day_names[best_dow]}s consistently deliver your best prices — {pct_diff}% higher than other days over the last 90 days.",
                }))

    # --- Price volatility: species with big swings recently ---
    species_recent: dict[str, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg and hist_date in recent_dates[:5]:
            canonical = normalise_species(species)
            species_recent[canonical].append(avg)

    for species, prices in species_recent.items():
        if len(prices) >= 3:
            pmin, pmax = min(prices), max(prices)
            if pmin > 0:
                volatility = ((pmax - pmin) / pmin) * 100
                if volatility > 15:
                    _ranked_port.append((2, {
                        "category": "VOLATILITY",
                        "text": f"{species} swung {volatility:.0f}% this week (£{pmin:.2f}–£{pmax:.2f}) — high volatility may signal changing supply or demand.",
                    }))
                    break

    # --- Species count trend ---
    species_by_date: dict[str, set] = defaultdict(set)
    for hist_date, species, *_ in history:
        species_by_date[hist_date].add(normalise_species(species))
    if len(recent_dates) >= 3:
        recent_counts = [len(species_by_date.get(d, set())) for d in recent_dates[:3]]
        older_counts = [len(species_by_date.get(d, set())) for d in recent_dates[3:] if d in species_by_date]
        if older_counts:
            recent_avg = sum(recent_counts) / len(recent_counts)
            older_avg = sum(older_counts) / len(older_counts)
            if recent_avg > older_avg + 2:
                _ranked_port.append((3, {
                    "category": "GROWTH",
                    "text": f"You're listing more species recently — averaging {recent_avg:.0f} per session vs {older_avg:.0f} earlier this month.",
                }))
            elif older_avg > recent_avg + 2:
                _ranked_port.append((3, {
                    "category": "WATCH",
                    "text": f"Species count has dropped — {recent_avg:.0f} per session recently vs {older_avg:.0f} earlier. Worth checking if landings are diversifying elsewhere.",
                }))

    # --- Highest-value species this port: which species earns the most per kg? ---
    species_avg_30d: dict[str, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            canonical = normalise_species(species)
            species_avg_30d[canonical].append(avg)
    if species_avg_30d:
        top_value = max(
            species_avg_30d.items(),
            key=lambda x: sum(x[1]) / len(x[1]),
        )
        top_sp, top_prices = top_value
        top_avg = sum(top_prices) / len(top_prices)
        _ranked_port.append((4, {
            "category": "STRENGTH",
            "text": f"{top_sp} is your highest-value species — averaging £{top_avg:.2f}/kg over the last 90 days.",
        }))

    # --- Price direction: is the port's overall average trending up or down? ---
    if len(recent_dates) >= 6:
        first_3 = recent_dates[:3]
        last_3 = recent_dates[3:6]
        first_prices = [
            avg for d, _, _, _, _, avg in history
            if d in first_3 and avg
        ]
        last_prices = [
            avg for d, _, _, _, _, avg in history
            if d in last_3 and avg
        ]
        if first_prices and last_prices:
            first_avg = sum(first_prices) / len(first_prices)
            last_avg = sum(last_prices) / len(last_prices)
            if last_avg > 0:
                trend_pct = ((first_avg - last_avg) / last_avg) * 100
                if abs(trend_pct) > 3:
                    direction = "up" if trend_pct > 0 else "down"
                    _ranked_port.append((5, {
                        "category": "TREND",
                        "text": f"Your overall average is trending {direction} — £{first_avg:.2f}/kg in the last 3 sessions vs £{last_avg:.2f} the 3 before that ({'+' if trend_pct > 0 else ''}{trend_pct:.1f}%).",
                    }))

    # ═══ MARKET INTELLIGENCE — this port vs the market ═══

    # --- Best performer vs market today ---
    best_today = None
    best_vs = -999
    for item in today_data:
        if item["position"] and item["position"]["vs_pct"] > best_vs:
            best_vs = item["position"]["vs_pct"]
            best_today = item
    if best_today and best_vs > 3:
        _ranked_market.append((1, {
            "category": "STRENGTH",
            "text": f"{best_today['species']} outperformed the UK average by {best_vs:.1f}% today — your strongest species against the market.",
        }))

    # --- Worst performer vs market today ---
    worst_today = None
    worst_vs = 999
    for item in today_data:
        if item["position"] and item["position"]["vs_pct"] < worst_vs:
            worst_vs = item["position"]["vs_pct"]
            worst_today = item
    if worst_today and worst_vs < -5:
        _ranked_market.append((4, {
            "category": "WATCH",
            "text": f"{worst_today['species']} came in {abs(worst_vs):.1f}% below the UK average today — worth checking grade mix or timing.",
        }))

    # --- Consistent outperformer: species beating market 20+ of last 30 days ---
    species_above_30d: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    last_30_dates = [d for d in recent_dates if len(recent_dates) <= 30 or d >= recent_dates[29]]
    for hist_date in last_30_dates:
        day_market = get_market_averages_for_date(hist_date)
        for h_date, species, _grade, _low, _high, avg in history:
            if h_date == hist_date and avg:
                canonical = normalise_species(species)
                mkt = day_market.get(canonical, {})
                if mkt.get("avg") and mkt["avg"] > 0:
                    above, total = species_above_30d[canonical]
                    total += 1
                    if avg > mkt["avg"]:
                        above += 1
                    species_above_30d[canonical] = (above, total)

    best_consistent = None
    best_consistency = 0
    for sp, (above, total) in species_above_30d.items():
        if total >= 15 and above >= 20 and above > best_consistency:
            best_consistent = sp
            best_consistency = above

    if best_consistent:
        above, total = species_above_30d[best_consistent]
        _ranked_market.append((2, {
            "category": "STRENGTH",
            "text": f"{best_consistent} is your most reliable market-beater — above UK average on {above} of the last {total} trading days.",
        }))

    # --- Best species vs market this week ---
    week_dates = recent_dates[:5]
    species_week_spread: dict[str, list[float]] = defaultdict(list)
    for hist_date in week_dates:
        day_market = get_market_averages_for_date(hist_date)
        for h_date, species, _grade, _low, _high, avg in history:
            if h_date == hist_date and avg:
                canonical = normalise_species(species)
                mkt = day_market.get(canonical, {})
                if mkt.get("avg") and mkt["avg"] > 0:
                    spread = ((avg - mkt["avg"]) / mkt["avg"]) * 100
                    species_week_spread[canonical].append(spread)

    best_week_sp = None
    best_week_avg = -999
    for sp, spreads in species_week_spread.items():
        if len(spreads) >= 2:
            avg_spread = sum(spreads) / len(spreads)
            if avg_spread > best_week_avg:
                best_week_avg = avg_spread
                best_week_sp = sp

    if best_week_sp and best_week_avg > 3:
        _ranked_market.append((3, {
            "category": "STRENGTH",
            "text": f"{best_week_sp} had the widest margin over market this week — averaging +{best_week_avg:.1f}% across {len(species_week_spread[best_week_sp])} sessions.",
        }))

    # --- Species below market for multiple days ---
    species_below_streak: dict[str, int] = defaultdict(int)
    for hist_date in recent_dates[:5]:
        day_market = get_market_averages_for_date(hist_date)
        for h_date, species, _grade, _low, _high, avg in history:
            if h_date == hist_date and avg:
                canonical = normalise_species(species)
                mkt = day_market.get(canonical, {})
                if mkt.get("avg") and avg < mkt["avg"] * 0.95:
                    species_below_streak[canonical] += 1

    for species, count in species_below_streak.items():
        if count >= 3:
            _ranked_market.append((5, {
                "category": "WATCH",
                "text": f"{species} has traded below market for {count} of the last 5 sessions — consider whether grade distribution or volumes are affecting price.",
            }))
            break

    # --- Overall market position ---
    all_today_prices = [info["avg"] for info in market.values() if info.get("avg")]
    if all_today_prices:
        market_avg_today = sum(all_today_prices) / len(all_today_prices)
        port_avg = sum(
            item["price_avg"] for item in today_data if item["price_avg"]
        ) / max(1, len([i for i in today_data if i["price_avg"]]))
        if port_avg > market_avg_today * 1.05:
            pct_above = ((port_avg - market_avg_today) / market_avg_today) * 100
            _ranked_market.append((6, {
                "category": "POSITION",
                "text": f"Your average today (£{port_avg:.2f}/kg) is {pct_above:.0f}% above the UK-wide average — a strong position for attracting landings.",
            }))
        elif port_avg < market_avg_today * 0.95:
            pct_below = ((market_avg_today - port_avg) / market_avg_today) * 100
            _ranked_market.append((6, {
                "category": "POSITION",
                "text": f"Your average today (£{port_avg:.2f}/kg) is {pct_below:.0f}% below the UK-wide average — worth reviewing whether grade mix or species composition is a factor.",
            }))

    # --- Missing opportunity: species in market but not at this port ---
    port_species = {item["species"] for item in today_data}
    for species, info in market.items():
        canonical = normalise_species(species)
        if canonical not in port_species and info["port_count"] >= 2 and info["avg"] > 5.0:
            _ranked_market.append((7, {
                "category": "OPPORTUNITY",
                "text": f"{canonical} traded at £{info['avg']:.2f} across {info['port_count']} ports today — a gap in your listings worth investigating.",
            }))

    # --- Biggest spread in market ---
    max_spread_species = None
    max_spread_pct = 0
    for species, info in market.items():
        if info["port_count"] >= 2 and info["min"] > 0:
            spread_pct = ((info["max"] - info["min"]) / info["min"]) * 100
            if spread_pct > max_spread_pct:
                max_spread_pct = spread_pct
                max_spread_species = normalise_species(species)
    if max_spread_species and max_spread_pct > 15:
        _ranked_market.append((8, {
            "category": "SPREAD",
            "text": f"{max_spread_species} has the widest UK spread today at {max_spread_pct:.0f}% — buyers looking for value may shift to cheaper ports.",
        }))

    # Sort by priority and cap at 3 each
    _ranked_port.sort(key=lambda x: x[0])
    _ranked_market.sort(key=lambda x: x[0])

    return {
        "port": [item for _, item in _ranked_port[:3]],
        "market": [item for _, item in _ranked_market[:3]],
    }


def _build_category_stats(
    today_data: list[dict],
    last_week_prices: dict,
    market: dict,
    history: list[tuple],
) -> dict:
    """Compute per-category hero stats for the category pill filter.

    Returns a dict keyed by category slug ('all', 'demersal', etc.) with:
    today_avg, vs_last_week, last_week_price, vs_market,
    week_avg, week_change, month_avg, month_change.
    """
    from collections import defaultdict

    _CATEGORIES = ["all", "demersal", "flatfish", "shellfish", "pelagic", "other"]

    # Build history date buckets for week/month rolling windows
    date_cat_prices: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            canonical = normalise_species(species)
            cat = get_species_category(canonical)
            date_cat_prices[hist_date]["all"].append(avg)
            date_cat_prices[hist_date][cat].append(avg)

    sorted_dates = sorted(date_cat_prices.keys(), reverse=True)
    this_week_dates = sorted_dates[:5]
    last_week_dates = sorted_dates[5:10]
    this_month_dates = sorted_dates[:20]
    last_month_dates = sorted_dates[20:40]

    def _period_avg(dates: list[str], cat: str) -> float | None:
        prices = [p for d in dates for p in date_cat_prices.get(d, {}).get(cat, [])]
        return round(sum(prices) / len(prices), 2) if prices else None

    # Build last_week raw-species → category mapping from today_data
    raw_to_cat = {item["raw_species"]: item["category"] for item in today_data}

    result = {}
    for cat in _CATEGORIES:
        # Today's avg for this category
        today_prices = [
            item["price_avg"] for item in today_data
            if item["price_avg"] and (cat == "all" or item["category"] == cat)
        ]
        today_avg = round(sum(today_prices) / len(today_prices), 2) if today_prices else None

        # vs last week: match last-week species to category using raw_to_cat
        lw_prices_cat = [
            v["price_avg"] for (sp, _gr), v in last_week_prices.items()
            if v["price_avg"] and (
                cat == "all" or
                raw_to_cat.get(sp, get_species_category(normalise_species(sp))) == cat
            )
        ]
        vs_last_week = None
        last_week_price = None
        if lw_prices_cat and today_prices:
            lw_avg = sum(lw_prices_cat) / len(lw_prices_cat)
            td_avg = sum(today_prices) / len(today_prices)
            if lw_avg > 0:
                vs_last_week = round(((td_avg - lw_avg) / lw_avg) * 100, 1)
            last_week_price = round(lw_avg, 2)

        # vs UK market: filter market to species in this category
        port_species_in_cat = {item["species"] for item in today_data if cat == "all" or item["category"] == cat}
        mkt_avgs = [
            info["avg"] for sp, info in market.items()
            if info.get("avg") and sp in port_species_in_cat
        ]
        vs_market = None
        if mkt_avgs and today_prices:
            mkt_overall = sum(mkt_avgs) / len(mkt_avgs)
            port_overall = sum(today_prices) / len(today_prices)
            if mkt_overall > 0:
                vs_market = round(((port_overall - mkt_overall) / mkt_overall) * 100, 1)

        # Rolling week/month averages from history
        this_week_avg = _period_avg(this_week_dates, cat)
        prev_week_avg = _period_avg(last_week_dates, cat)
        week_change = None
        if this_week_avg and prev_week_avg and prev_week_avg > 0:
            week_change = round(((this_week_avg - prev_week_avg) / prev_week_avg) * 100, 1)

        this_month_avg = _period_avg(this_month_dates, cat)
        prev_month_avg = _period_avg(last_month_dates, cat)
        month_change = None
        if this_month_avg and prev_month_avg and prev_month_avg > 0:
            month_change = round(((this_month_avg - prev_month_avg) / prev_month_avg) * 100, 1)

        result[cat] = {
            "today_avg": today_avg,
            "vs_last_week": vs_last_week,
            "last_week_price": last_week_price,
            "vs_market": vs_market,
            "week_avg": this_week_avg,
            "week_change": week_change,
            "month_avg": this_month_avg,
            "month_change": month_change,
        }

    return result


def _build_performance_overview(
    port_name: str, date: str, history: list[tuple], market: dict,
) -> dict:
    """Build week-over-week and month-over-month performance metrics."""
    from collections import defaultdict
    from datetime import datetime as dt, timedelta

    # Group history by date → list of avg prices
    date_prices: dict[str, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            date_prices[hist_date].append(avg)

    sorted_dates = sorted(date_prices.keys(), reverse=True)

    # Split into this week (last 5 trading days) and last week (5 before that)
    this_week_dates = sorted_dates[:5]
    last_week_dates = sorted_dates[5:10]

    def _period_avg(dates: list[str]) -> float | None:
        prices = [p for d in dates for p in date_prices.get(d, [])]
        return round(sum(prices) / len(prices), 2) if prices else None

    this_week_avg = _period_avg(this_week_dates)
    last_week_avg = _period_avg(last_week_dates)

    week_change = None
    if this_week_avg and last_week_avg and last_week_avg > 0:
        week_change = round(((this_week_avg - last_week_avg) / last_week_avg) * 100, 1)

    # Month-over-month: last 20 trading days vs 20 before that
    this_month_dates = sorted_dates[:20]
    last_month_dates = sorted_dates[20:40]

    this_month_avg = _period_avg(this_month_dates)
    last_month_avg = _period_avg(last_month_dates)

    month_change = None
    if this_month_avg and last_month_avg and last_month_avg > 0:
        month_change = round(((this_month_avg - last_month_avg) / last_month_avg) * 100, 1)

    # Market position trend: avg vs-market % this week vs last week
    def _market_position(dates: list[str]) -> float | None:
        vs_pcts = []
        for d in dates:
            day_market = get_market_averages_for_date(d)
            for h_date, species, _grade, _low, _high, avg in history:
                if h_date == d and avg:
                    canonical = normalise_species(species)
                    mkt = day_market.get(canonical, {})
                    if mkt.get("avg") and mkt["avg"] > 0:
                        vs_pcts.append(((avg - mkt["avg"]) / mkt["avg"]) * 100)
        return round(sum(vs_pcts) / len(vs_pcts), 1) if vs_pcts else None

    mkt_pos_this_week = _market_position(this_week_dates)
    mkt_pos_last_week = _market_position(last_week_dates)

    mkt_trend = None
    if mkt_pos_this_week is not None and mkt_pos_last_week is not None:
        mkt_trend = round(mkt_pos_this_week - mkt_pos_last_week, 1)

    # Species count trend
    this_week_species = set()
    last_week_species = set()
    for d in this_week_dates:
        for h_date, species, *_ in history:
            if h_date == d:
                this_week_species.add(normalise_species(species))
    for d in last_week_dates:
        for h_date, species, *_ in history:
            if h_date == d:
                last_week_species.add(normalise_species(species))

    # Trading sessions this week vs last
    sessions_this_week = len(this_week_dates)
    sessions_last_week = len(last_week_dates)

    # Volume (boxes) from landings table if available
    from quayside.db import get_connection
    conn = get_connection()

    def _boxes_for_dates(dates: list[str]) -> int | None:
        if not dates:
            return None
        placeholders = ",".join("?" for _ in dates)
        try:
            row = conn.execute(
                f"""SELECT SUM(boxes) FROM landings
                    WHERE port = ? AND date IN ({placeholders})""",
                [port_name] + dates,
            ).fetchone()
            return row[0] if row and row[0] else None
        except sqlite3.OperationalError:
            return None

    total_boxes = _boxes_for_dates(this_week_dates)
    last_week_boxes = _boxes_for_dates(last_week_dates)
    conn.close()

    boxes_change = None
    if total_boxes and last_week_boxes and last_week_boxes > 0:
        boxes_change = round(((total_boxes - last_week_boxes) / last_week_boxes) * 100, 1)

    return {
        "this_week_avg": this_week_avg,
        "last_week_avg": last_week_avg,
        "week_change": week_change,
        "this_month_avg": this_month_avg,
        "last_month_avg": last_month_avg,
        "month_change": month_change,
        "mkt_pos_this_week": mkt_pos_this_week,
        "mkt_pos_last_week": mkt_pos_last_week,
        "mkt_trend": mkt_trend,
        "species_this_week": len(this_week_species),
        "species_last_week": len(last_week_species),
        "sessions_this_week": sessions_this_week,
        "sessions_last_week": sessions_last_week,
        "total_boxes": total_boxes,
        "last_week_boxes": last_week_boxes,
        "boxes_change": boxes_change,
    }


def _format_data_freshness(scraped_at: str | None, auction_date: str) -> dict:
    """Return a dict describing how fresh the data is for display in the header.

    Returns: {label: str, status: 'live'|'recent'|'stale', tooltip: str}
    """
    from datetime import datetime as dt, timezone

    now = dt.now()
    today_str = now.strftime("%Y-%m-%d")

    if not scraped_at:
        return {"label": "No data", "status": "stale", "tooltip": "No data available"}

    try:
        # scraped_at may be a full ISO datetime or just a date
        if "T" in scraped_at:
            scraped_dt = dt.fromisoformat(scraped_at)
        else:
            scraped_dt = dt.strptime(scraped_at, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {"label": "Data available", "status": "recent", "tooltip": scraped_at}

    hours_ago = (now - scraped_dt).total_seconds() / 3600

    if auction_date == today_str:
        if hours_ago < 1:
            label = f"Updated {int((now - scraped_dt).total_seconds() / 60)}m ago"
            status = "live"
        elif hours_ago < 12:
            label = f"Updated {scraped_dt.strftime('%H:%M')} today"
            status = "live"
        else:
            label = f"Today's data · scraped {scraped_dt.strftime('%H:%M')}"
            status = "live"
        tooltip = f"Data last updated {scraped_dt.strftime('%-d %b %Y at %H:%M')}"
    elif hours_ago < 48:
        label = f"Yesterday's auction · {scraped_dt.strftime('%H:%M')}"
        status = "recent"
        tooltip = f"Last updated {scraped_dt.strftime('%-d %b %Y at %H:%M')}"
    else:
        days_ago = int(hours_ago / 24)
        label = f"{days_ago}d old · {auction_date}"
        status = "stale"
        tooltip = f"Data from {auction_date}, last updated {scraped_dt.strftime('%-d %b %Y at %H:%M')}"

    return {"label": label, "status": status, "tooltip": tooltip}


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
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
