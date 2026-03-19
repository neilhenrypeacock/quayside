"""Trade blueprint — trade dashboard, export, chat, ports, feedback, compare."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, render_template, request

from quayside.db import (
    get_all_ports,
    get_last_scrape_info,
    get_latest_rich_date,
    get_prices_for_date_range,
    insert_trade_feedback,
)
from quayside.species import normalise_species
from quayside.web.helpers import build_scrape_info_display

trade_bp = Blueprint("trade", __name__)

TRADE_TOKEN = os.environ.get("QUAYSIDE_TRADE_TOKEN", "")


def _check_trade_access() -> bool:
    """Return True if the request has a valid trade access token/cookie."""
    if not TRADE_TOKEN:
        return True
    token = request.args.get("token") or request.cookies.get("trade_access")
    return token == TRADE_TOKEN


@trade_bp.route("/trade")
@trade_bp.route("/trade/<date>")
def trade_dashboard(date: str | None = None):
    from flask import current_app
    from quayside.trade import build_trade_data

    if not _check_trade_access():
        return render_template("trade_gate.html"), 403

    actual_today = datetime.now().strftime("%Y-%m-%d")
    if date is None:
        date = get_latest_rich_date()
    if not date:
        return "No data available", 404

    raw_ports_param = request.args.get("ports", None)
    if raw_ports_param is None:
        selected_ports = None
    else:
        selected_ports = [p.strip() for p in raw_ports_param.split(",") if p.strip()]

    is_fallback = (date != actual_today)
    scrape_info = get_last_scrape_info()
    scrape_info_display = build_scrape_info_display(scrape_info)
    if not is_fallback:
        freshness_status = "live"
    elif scrape_info["last_checked"]:
        hours_since = (datetime.now() - datetime.fromisoformat(scrape_info["last_checked"])).total_seconds() / 3600
        freshness_status = "stale" if hours_since < 4 else "offline"
    else:
        freshness_status = "offline"

    data = build_trade_data(date, selected_ports=selected_ports)
    data["is_fallback"] = is_fallback
    data["actual_today"] = actual_today
    data["freshness_status"] = freshness_status
    data["scrape_info"] = scrape_info_display

    response = current_app.make_response(render_template("trade.html", **data))

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


@trade_bp.route("/trade/export")
def trade_export():
    """Download filtered price data as CSV."""
    import csv
    import io

    if not _check_trade_access():
        return "Access denied", 403

    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    species_filter = request.args.get("species", "").strip().lower()
    port_filter = request.args.get("port", "").strip()
    ports_param = request.args.get("ports", "").strip()
    ports_filter_set: set[str] | None = None
    if port_filter:
        ports_filter_set = {port_filter}
    elif ports_param:
        ports_filter_set = {p.strip() for p in ports_param.split(",") if p.strip()}

    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    rows = get_prices_for_date_range(date_from, date_to)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Port", "Raw Species", "Canonical Species",
                     "Grade", "Price Low", "Price High", "Price Avg"])
    for date_val, port, species, grade, low, high, avg in rows:
        canonical = normalise_species(species)
        if canonical is None:
            continue
        if species_filter and canonical.lower() != species_filter:
            continue
        if ports_filter_set and port not in ports_filter_set:
            continue
        writer.writerow([date_val, port, species, canonical, grade,
                         f"{low:.2f}" if low is not None else "",
                         f"{high:.2f}" if high is not None else "",
                         f"{avg:.2f}" if avg is not None else ""])

    if port_filter:
        name_slug = port_filter.lower().replace(" ", "_")
        filename = f"quayside_{name_slug}_{date_from}_{date_to}.csv"
    elif species_filter:
        name_slug = species_filter.replace(" ", "_")
        filename = f"quayside_{name_slug}_{date_from}_{date_to}.csv"
    else:
        filename = f"quayside_trade_{date_from}_{date_to}.csv"

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _call_chat_api(system_prompt: str, user_message: str) -> tuple[str, int]:
    """Shared chat handler — calls Claude Haiku and returns (reply_text, status_code)."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Chatbot unavailable — ANTHROPIC_API_KEY not set.", 200

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    reply = message.content[0].text if message.content else "No response."
    return reply, 200


@trade_bp.route("/trade/chat", methods=["POST"])
def trade_chat():
    """Chatbot endpoint — calls Claude with fish market context."""
    if not _check_trade_access():
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    context = data.get("context") or {}

    if not user_message:
        return jsonify({"error": "No message"}), 400

    system_prompt = (
        "You are a knowledgeable fish market analyst assistant for Quayside, "
        "a UK fish auction price aggregator covering ports including Peterhead, Brixham, "
        "Newlyn, Scrabster, and Lerwick. You help fish buyers and sellers interpret price data, "
        "identify arbitrage opportunities, understand market trends, and make informed purchasing "
        "decisions. Prices are in £/kg. Be concise, practical, and specific. "
        "Use proper fish names (e.g. Monkfish not Monks). "
    )

    if context:
        date_ctx = context.get("date", "")
        species_ctx = context.get("selected_species", "")
        prices_ctx = context.get("top_prices", [])
        if date_ctx:
            system_prompt += f"\n\nCurrent dashboard date: {date_ctx}."
        if species_ctx:
            system_prompt += f" User is viewing: {species_ctx}."
        if prices_ctx:
            price_lines = "; ".join(
                f"{p.get('species')} mkt avg £{p.get('market_avg', 0):.2f}/kg "
                f"(spread {p.get('spread_pct', 0):.0f}%)"
                for p in prices_ctx[:8]
            )
            system_prompt += f"\n\nToday's top prices: {price_lines}."

    reply, status = _call_chat_api(system_prompt, user_message)
    return jsonify({"reply": reply}), status


@trade_bp.route("/trade/ports")
def trade_ports():
    """Port contacts directory for trade subscribers."""
    if not _check_trade_access():
        return render_template("trade_gate.html"), 403

    _PORT_INFO = {
        "peterhead": {
            "auction_time": "Mon-Fri from 07:00",
            "contact_phone": "+44 1779 474020",
            "website": "https://www.peterheadportauthority.com",
            "description": "Europe's largest white fish market. Daily auctions Mon-Fri.",
        },
        "brixham": {
            "auction_time": "Mon-Fri from 06:00",
            "contact_phone": "+44 1803 882985",
            "website": "https://www.brixhamfishmarket.co.uk",
            "description": "One of the UK's most valuable fishing ports. Mixed demersal and shellfish.",
        },
        "newlyn": {
            "auction_time": "Mon-Sat from 07:00",
            "contact_phone": "+44 1736 362711",
            "website": "https://www.newlynfish.co.uk",
            "description": "Cornwall's premier fish market. Strong on day-boat landings.",
        },
        "scrabster": {
            "auction_time": "Mon-Fri from 08:00",
            "contact_phone": "+44 1847 893285",
            "website": "https://www.scrabster.co.uk",
            "description": "North Scotland's main demersal market. Strong Haddock and Monkfish.",
        },
        "lerwick": {
            "auction_time": "Mon-Fri, times vary",
            "contact_phone": "+44 1595 692991",
            "website": "https://www.lerwick-harbour.co.uk",
            "description": "Shetland's main port. Strong pelagic and shellfish landings.",
        },
        "fraserburgh": {
            "auction_time": "Mon-Fri from 07:00",
            "contact_phone": "+44 1346 515858",
            "website": "https://www.fraserburgh-harbour.co.uk",
            "description": "Major North-East Scotland market. Currently in outreach for data partnership.",
        },
    }

    active_ports = [p for p in get_all_ports(status="active") if p.get("data_method") != "demo"]
    outreach_ports = [
        p for p in get_all_ports() if p.get("status") == "outreach"
    ]

    def _enrich(port_list):
        result = []
        for p in port_list:
            info = _PORT_INFO.get(p["slug"], {})
            result.append({**p, **info})
        return result

    return render_template(
        "trade_ports.html",
        active_ports=_enrich(active_ports),
        outreach_ports=_enrich(outreach_ports),
    )


@trade_bp.route("/trade/feedback", methods=["POST"])
def trade_feedback():
    """Store a trade dashboard feature request / feedback submission."""
    if not _check_trade_access():
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:100]
    message = (data.get("message") or "").strip()[:2000]
    page_context = (data.get("page_context") or "").strip()[:200]

    if not message:
        return jsonify({"error": "Message required"}), 400

    insert_trade_feedback(name, message, page_context)
    return jsonify({"ok": True})


@trade_bp.route("/trade/compare")
def trade_compare():
    """Return compare matrix JSON for two dates."""
    from quayside.trade import build_compare_data

    if not _check_trade_access():
        return jsonify({"error": "Access denied"}), 403

    date_a = request.args.get("date_a", "")
    date_b = request.args.get("date_b", "")
    if not date_a or not date_b:
        return jsonify({"error": "date_a and date_b required"}), 400

    data = build_compare_data(date_a, date_b)
    return jsonify(data)
