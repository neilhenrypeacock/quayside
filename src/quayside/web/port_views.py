"""Port blueprint — dashboards, prices, ranking, compare, upload, confirm, export."""

from __future__ import annotations

import json
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from quayside.confirm import generate_confirm_token, get_upload_for_token
from quayside.db import (
    confirm_upload,
    create_upload,
    get_all_ports,
    get_latest_date,
    get_latest_port_date,
    get_latest_scraped_at,
    get_last_scrape_info,
    get_market_averages_for_date,
    get_market_averages_for_range,
    get_port,
    get_port_auction_dates,
    get_port_by_token,
    get_port_prices_history,
    get_prices_by_date,
    get_prices_for_date_range,
    get_same_day_last_week,
    get_seasonal_comparison,
    get_species_availability_gaps,
    get_upload,
    log_correction,
    upsert_prices_with_upload,
)
from quayside.extractors import extract_from_file
from quayside.models import PriceRecord
from quayside.species import get_all_canonical_names, normalise_species
from quayside.web.helpers import (
    build_best_performers,
    build_category_stats,
    build_competitive_market,
    build_competitive_summary,
    build_insights,
    build_missing_species,
    build_performance_overview,
    build_scrape_info_display,
    build_smart_alerts,
    build_today_data,
    build_trend_data,
    format_data_freshness,
    parse_form_prices,
)

port_bp = Blueprint("ports", __name__)

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"


@port_bp.route("/port/<slug>")
def port_dashboard(slug: str):
    """Port dashboard — shows their data + market position."""
    from flask import current_app

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
    actual_today = datetime.now().strftime("%Y-%m-%d")
    explicitly_requested_date = request.args.get("date")
    date = explicitly_requested_date or latest

    available_dates = get_port_auction_dates(port["name"], limit=20)

    compare_date_param = request.args.get("compare")

    port_prices = get_prices_by_date(date, port["name"])

    is_fallback = False
    if not port_prices and not explicitly_requested_date:
        fallback_date = get_latest_port_date(port["name"])
        if fallback_date and fallback_date != date:
            date = fallback_date
            port_prices = get_prices_by_date(date, port["name"])
            is_fallback = True

    market = get_market_averages_for_date(date)

    if compare_date_param and compare_date_param != date:
        last_week_prices = {
            (r[2], r[3]): {"price_avg": r[6], "price_low": r[4], "price_high": r[5]}
            for r in get_prices_by_date(compare_date_param, port["name"])
        }
    else:
        last_week_prices = get_same_day_last_week(port["name"], date)

    today_data = build_today_data(port_prices, market, last_week_prices)

    history = get_port_prices_history(port["name"], days=90)
    history_days = len({h[0] for h in history})
    # Constrain market averages to actual data span, not an arbitrary 90-day window
    if history:
        _history_start = min(h[0] for h in history)
    else:
        _history_start = (
            datetime.strptime(date, "%Y-%m-%d") - timedelta(days=90)
        ).strftime("%Y-%m-%d")
    market_avgs_range = get_market_averages_for_range(_history_start, date)
    trend_data = build_trend_data(history, market_avgs_range)

    best_performers = build_best_performers(port["name"], date, days=30)
    all_insights = build_insights(port["name"], date, today_data, history)

    species_grades = OrderedDict()
    for item in today_data:
        sp = item["species"]
        if sp not in species_grades:
            species_grades[sp] = []
        species_grades[sp].append(item)

    volume_type = "boxes" if port["slug"] == "scrabster" else "weight"
    has_volume = any(
        (item.get("weight_kg") and item["weight_kg"] > 0) or
        (item.get("boxes") and item["boxes"] > 0)
        for item in today_data
    )

    avg_prices = [item["price_avg"] for item in today_data if item["price_avg"]]
    hero_avg_price = round(sum(avg_prices) / len(avg_prices), 2) if avg_prices else None

    hero_species_count = len(species_grades)

    above_count = sum(
        1 for items in species_grades.values()
        if items[0]["position"] and items[0]["position"]["vs_pct"] > 0
    )

    hero_vs_last_week = None
    hero_last_week_price = None
    if last_week_prices:
        lw_avgs = [v["price_avg"] for v in last_week_prices.values() if v["price_avg"]]
        if lw_avgs and avg_prices:
            lw_overall = sum(lw_avgs) / len(lw_avgs)
            today_overall = sum(avg_prices) / len(avg_prices)
            if lw_overall > 0:
                hero_vs_last_week = round(((today_overall - lw_overall) / lw_overall) * 100, 1)
            hero_last_week_price = round(lw_overall, 2)

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
            hero_vs_market = round(((port_overall - market_overall) / market_overall) * 100, 1)

    species_gaps = [
        normalise_species(s)
        for s in get_species_availability_gaps(port["name"], date)
        if normalise_species(s) is not None
    ]

    seasonal_raw = get_seasonal_comparison(port["name"], date)
    seasonal_data = {
        normalise_species(sp): price
        for sp, price in seasonal_raw.items()
        if normalise_species(sp) is not None
    }
    has_seasonal = bool(seasonal_data)

    try:
        _dt = datetime.strptime(date, "%Y-%m-%d")
        day_name = _dt.strftime("%A")[:3]
        latest_date_display = _dt.strftime("%-d %b %Y")
    except ValueError:
        day_name = "Week"
        latest_date_display = date

    if compare_date_param and compare_date_param != date:
        try:
            _cdt = datetime.strptime(compare_date_param, "%Y-%m-%d")
            compare_label = _cdt.strftime("%-d %b")
        except ValueError:
            compare_label = compare_date_param
        compare_date_display = compare_date_param
    else:
        compare_label = f"last {day_name}"
        compare_date_display = None

    scraped_at_raw = get_latest_scraped_at(port["name"], date)
    data_freshness = format_data_freshness(scraped_at_raw, date)

    scrape_info = get_last_scrape_info()
    scrape_info_display = build_scrape_info_display(scrape_info)
    if today_data and date == actual_today:
        freshness_status = "live"
    elif scrape_info["last_checked"]:
        hours_since = (datetime.now() - datetime.fromisoformat(scrape_info["last_checked"])).total_seconds() / 3600
        freshness_status = "stale" if hours_since < 4 else "offline"
    else:
        freshness_status = "offline"

    perf = build_performance_overview(port["name"], date, history, market)
    category_stats = build_category_stats(today_data, last_week_prices, market, history)

    # Phase 1: Competitive position, smart alerts, missing species
    competitive = build_competitive_market(port["name"], date)
    competitive_summary = build_competitive_summary(competitive)
    smart_alerts = build_smart_alerts(port["name"], date, "port")
    missing_species = build_missing_species(port["name"], date)

    # Fluid data fields — detect what data this port provides
    port_capabilities = {
        "has_volume": any(
            (item.get("weight_kg") and item["weight_kg"] > 0)
            for item in today_data
        ),
        "has_ranges": any(
            item.get("price_low") is not None
            for item in today_data
        ),
        "has_boxes": any(
            (item.get("boxes") and item["boxes"] > 0)
            for item in today_data
        ),
    }

    response = current_app.make_response(render_template(
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
        is_fallback=is_fallback,
        actual_today=actual_today,
        freshness_status=freshness_status,
        scrape_info=scrape_info_display,
        has_volume=has_volume,
        volume_type=volume_type,
        competitive=competitive,
        competitive_summary=competitive_summary,
        smart_alerts=smart_alerts,
        missing_species=missing_species,
        port_capabilities=port_capabilities,
        chat_endpoint=f"/port/{slug}/chat",
        chat_pills=[
            "How does our haddock compare to other ports this week?",
            "Which species are we consistently beating market on?",
            "What's our best performing day of the week?",
            "Show me our cod trend over the last 30 days",
        ],
    ))

    if request.args.get("token"):
        response.set_cookie(
            f"port_{slug}", request.args["token"],
            max_age=30 * 24 * 60 * 60,
            httponly=True, samesite="Lax",
        )

    return response


@port_bp.route("/port/<slug>/prices")
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

    today_data = build_today_data(port_prices, market, last_week_prices)

    species_grades = OrderedDict()
    for item in today_data:
        sp = item["species"]
        if sp not in species_grades:
            species_grades[sp] = []
        species_grades[sp].append(item)

    volume_type = "boxes" if port["slug"] == "scrabster" else "weight"
    has_volume = any(
        (item.get("weight_kg") and item["weight_kg"] > 0) or
        (item.get("boxes") and item["boxes"] > 0)
        for item in today_data
    )

    seasonal_raw = get_seasonal_comparison(port["name"], date)
    seasonal_data = {
        normalise_species(sp): price for sp, price in seasonal_raw.items()
        if normalise_species(sp) is not None
    }
    has_seasonal = bool(seasonal_data)

    try:
        _dt = datetime.strptime(date, "%Y-%m-%d")
        day_name = _dt.strftime("%A")[:3]
        latest_date_display = _dt.strftime("%-d %b %Y")
    except ValueError:
        day_name = "Week"
        latest_date_display = date

    if compare_date_param and compare_date_param != date:
        try:
            _cdt = datetime.strptime(compare_date_param, "%Y-%m-%d")
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
        has_volume=has_volume,
        volume_type=volume_type,
    )


@port_bp.route("/port/<slug>/api/ranking")
def port_ranking_api(slug: str):
    """Return per-species port ranking JSON for the competitive ranking panel."""
    from quayside.db import get_all_prices_for_date

    port = get_port(slug)
    if not port:
        return {"error": "Not found"}, 404

    latest = get_latest_date() or datetime.now().strftime("%Y-%m-%d")
    date = request.args.get("date") or latest
    species_filter = request.args.get("species", "").strip()
    try:
        days = max(1, int(request.args.get("days", 1)))
    except ValueError:
        days = 1

    if days <= 1:
        all_rows = get_all_prices_for_date(date)
    else:
        start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
        all_rows = get_prices_for_date_range(start, date)

    port_sp_prices: dict[tuple, list] = defaultdict(list)
    for _d, row_port, row_sp, _grade, _low, _high, row_avg, *_ in all_rows:
        if row_avg:
            canon = normalise_species(row_sp)
            if canon is None:
                continue
            port_sp_prices[(canon, row_port)].append(row_avg)

    this_port = port["name"]

    if species_filter:
        port_avgs = []
        for (canon, p_name), prices in port_sp_prices.items():
            if canon == species_filter:
                avg = sum(prices) / len(prices)
                port_avgs.append({"port": p_name, "avg": round(avg, 2),
                                  "is_this_port": p_name == this_port})
        if not port_avgs:
            return {"species": species_filter, "rows": [], "market_avg": None}
        port_avgs.sort(key=lambda r: r["avg"], reverse=True)
        market_avg = round(sum(r["avg"] for r in port_avgs) / len(port_avgs), 2)
        for i, row in enumerate(port_avgs):
            row["rank"] = i + 1
            row["vs_market_pct"] = round(
                ((row["avg"] - market_avg) / market_avg) * 100, 1
            )
        period = "Today" if days <= 1 else f"Last {days} days"
        return {"species": species_filter, "period": period,
                "market_avg": market_avg, "rows": port_avgs}

    else:
        results = []
        this_port_species = {
            canon for (canon, p_name) in port_sp_prices if p_name == this_port
        }
        for canon in sorted(this_port_species):
            my_prices = port_sp_prices.get((canon, this_port), [])
            if not my_prices:
                continue
            my_avg = sum(my_prices) / len(my_prices)
            all_avgs = sorted(
                (sum(p) / len(p))
                for (c, _p), p in port_sp_prices.items()
                if c == canon
            )
            total = len(all_avgs)
            rank = sum(1 for a in all_avgs if a >= my_avg)
            market_avg = sum(all_avgs) / total if all_avgs else None
            vs_market = round(((my_avg - market_avg) / market_avg) * 100, 1) \
                if market_avg else None
            results.append({
                "species": canon,
                "avg": round(my_avg, 2),
                "rank": rank,
                "total": total,
                "vs_market_pct": vs_market,
            })
        results.sort(key=lambda r: r["rank"])
        period = "Today" if days <= 1 else f"Last {days} days"
        return {"mode": "summary", "period": period, "rows": results}


@port_bp.route("/port/<slug>/api/compare")
def port_compare_api(slug: str):
    """Return price comparison JSON between two dates for this port."""
    port = get_port(slug)
    if not port:
        return {"error": "Not found"}, 404

    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    if not date_from or not date_to:
        return {"error": "Missing from/to params"}, 400

    rows_from = get_prices_by_date(date_from, port["name"])
    rows_to = get_prices_by_date(date_to, port["name"])

    def _best_per_species(rows):
        d: dict[str, float] = {}
        for _date, _port, sp, _grade, _low, _high, avg in rows:
            canon = normalise_species(sp)
            if canon is None:
                continue
            if avg and (canon not in d or avg > d[canon]):
                d[canon] = avg
        return d

    dict_from = _best_per_species(rows_from)
    dict_to = _best_per_species(rows_to)

    results = []
    for sp in sorted(set(dict_from) | set(dict_to)):
        pf = dict_from.get(sp)
        pt = dict_to.get(sp)
        change_abs = round(pt - pf, 2) if pf and pt else None
        change_pct = round(((pt - pf) / pf) * 100, 1) if pf and pt and pf > 0 else None
        results.append({
            "species": sp,
            "price_from": pf,
            "price_to": pt,
            "change_abs": change_abs,
            "change_pct": change_pct,
        })

    return {"date_from": date_from, "date_to": date_to, "rows": results}


@port_bp.route("/port/<slug>/upload", methods=["GET", "POST"])
def port_upload(slug: str):
    """Web form upload — fallback for ports that email photos/docs."""
    port = get_port(slug)
    if not port:
        return "Port not found", 404

    if request.method == "GET":
        return render_template("upload_form.html", port=port)

    date = request.form.get("date", datetime.now().strftime("%Y-%m-%d"))

    uploaded_file = request.files.get("file")
    if uploaded_file and uploaded_file.filename:
        safe_name = secure_filename(uploaded_file.filename)
        if not safe_name:
            flash("Invalid filename.")
            return redirect(url_for("ports.port_upload", slug=slug))
        port_dir = UPLOAD_DIR / slug / date
        port_dir.mkdir(parents=True, exist_ok=True)
        file_path = port_dir / safe_name
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
            return redirect(url_for("ports.confirm_upload_page", token=token))

        flash("Could not extract prices from that file. Please try a different format.")
        return redirect(url_for("ports.port_upload", slug=slug))

    records = parse_form_prices(request.form, port["name"], date)
    if records:
        upload_id = create_upload(
            port_slug=slug, date=date, method="web:form",
            record_count=len(records),
        )
        upsert_prices_with_upload(records, upload_id)
        confirm_upload(upload_id, confirmed_by="web_form")
        flash(f"Published {len(records)} prices for {date}.")
        return redirect(url_for("ports.port_dashboard", slug=slug))

    flash("No prices entered. Please fill in at least one row.")
    return redirect(url_for("ports.port_upload", slug=slug))


@port_bp.route("/confirm/<token>")
def confirm_upload_page(token: str):
    """Confirmation page — show extracted data for review."""
    upload_id = get_upload_for_token(token)
    if not upload_id:
        return "Invalid or expired confirmation link", 404

    upload = get_upload(upload_id)
    if not upload:
        return "Upload not found", 404

    port = get_port(upload["port_slug"])
    if not port:
        return "Port not found", 404

    prices = get_prices_by_date(upload["date"], port["name"])

    return render_template(
        "confirm.html",
        upload=upload, port=port, prices=prices, token=token,
    )


@port_bp.route("/confirm/<token>/approve", methods=["POST"])
def approve_upload(token: str):
    """Handle 'Looks good' confirmation."""
    upload_id = get_upload_for_token(token)
    if not upload_id:
        return "Invalid or expired confirmation link", 404

    confirm_upload(upload_id, confirmed_by=request.remote_addr)
    upload = get_upload(upload_id)
    port = get_port(upload["port_slug"]) if upload else None

    if port:
        return redirect(url_for("ports.port_dashboard", slug=port["slug"]))
    return "Confirmed — thank you!", 200


@port_bp.route("/confirm/<token>/edit", methods=["GET", "POST"])
def edit_upload(token: str):
    """Editable table for corrections."""
    upload_id = get_upload_for_token(token)
    if not upload_id:
        return "Invalid or expired confirmation link", 404

    upload = get_upload(upload_id)
    if not upload:
        return "Upload not found", 404

    port = get_port(upload["port_slug"])
    if not port:
        return "Port not found", 404
    prices = get_prices_by_date(upload["date"], port["name"])

    if request.method == "GET":
        return render_template(
            "edit.html",
            upload=upload, port=port, prices=prices, token=token,
        )

    corrected_records = parse_form_prices(request.form, port["name"], upload["date"])
    if corrected_records:
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

    return redirect(url_for("ports.port_dashboard", slug=port["slug"]))


@port_bp.route("/port/<slug>/export")
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
    writer.writerow(["Date", "Raw Species", "Canonical Species", "Grade", "Price Low", "Price High", "Price Avg"])
    for date, species, grade, low, high, avg in history:
        writer.writerow([date, species, normalise_species(species) or species, grade, low, high, avg])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=quayside_{slug}_prices.csv",
        },
    )


@port_bp.route("/port/<slug>/template")
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


@port_bp.route("/port/submit")
@port_bp.route("/port/<slug>/submit")
def port_submit(slug: str | None = None):
    """Price submission form — no login required."""
    ports = [p for p in get_all_ports(status="active") if p.get("data_method") != "demo"]
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


@port_bp.route("/port/<slug>/chat", methods=["POST"])
def port_chat(slug: str):
    """Port-scoped chatbot endpoint — calls Claude with this port's context."""
    from quayside.web.trade_views import _call_chat_api

    port = get_port(slug)
    if not port:
        return jsonify({"error": "Port not found"}), 404

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "No message"}), 400

    context = data.get("context") or {}
    species_count = context.get("species_count", 0)
    date = context.get("date", datetime.now().strftime("%Y-%m-%d"))

    system_prompt = (
        f"You are Quayside's AI market analyst for {port['name']}. "
        f"Answer questions about this port's prices, trends, and competitive position. "
        f"You have access to price data for {port['name']} and can compare against other UK ports. "
        f"Today's date: {date}. This port sold {species_count} species today. "
        f"Prices are in £/kg. Keep answers concise — 2-3 sentences max unless asked for detail. "
        f"Use proper fish names (e.g. Monkfish not Monks). "
    )

    prices_ctx = context.get("top_prices", [])
    if prices_ctx:
        price_lines = "; ".join(
            f"{p.get('species')} £{p.get('price_avg', 0):.2f}/kg"
            for p in prices_ctx[:10]
        )
        system_prompt += f"\n\nToday's prices at {port['name']}: {price_lines}."

    reply, status = _call_chat_api(system_prompt, user_message)
    return jsonify({"reply": reply}), status
