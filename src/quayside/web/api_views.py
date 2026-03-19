"""API blueprint — ingest and CSV export endpoints."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, request

from quayside.db import get_all_ports, get_connection, get_prices_by_date
from quayside.models import PriceRecord
from quayside.species import normalise_species

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)

_API_KEY = os.environ.get("QUAYSIDE_API_KEY", "")


@api_bp.route("/api/v1/ingest", methods=["POST"])
def api_ingest():
    """Accept manual price submissions as JSON.

    Payload: {port, date, rows: [{species, grade, price_avg, notes?}], overwrite?}
    Requires X-API-Key header (set QUAYSIDE_API_KEY env var).
    """
    if _API_KEY:
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided, _API_KEY):
            return jsonify({"error": "Invalid or missing API key."}), 401
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


@api_bp.route("/api/v1/export/csv")
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
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Query prices
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
    writer.writerow(["Date", "Port", "Raw Species", "Canonical Species", "Grade", "Price Low", "Price High", "Price Avg"])
    for row in rows:
        date_val, port, species, grade, low, high, avg = row
        writer.writerow([date_val, port, species, normalise_species(species) or species, grade, low, high, avg])

    # Build filename
    safe_port = port_name.lower().replace(" ", "_")
    filename = f"quayside_{safe_port}_{date_from}_{date_to}.csv"

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
