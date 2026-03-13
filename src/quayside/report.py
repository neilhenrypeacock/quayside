"""Generate the daily HTML digest report from SQLite data."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jinja2

from quayside.db import get_all_prices_for_date, get_latest_date

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

PORT_CODES = {
    "Peterhead": "PTH",
    "Brixham": "BRX",
    "Scrabster": "SCR",
    "Newlyn": "NLN",
    "Lerwick": "LWK",
    "Fraserburgh": "FRB",
    "Kinlochbervie": "KLB",
}


def _build_report_data(date: str) -> dict:
    """Query DB and assemble template context for the given date."""
    rows = get_all_prices_for_date(date)  # (date, port, species, grade, low, high, avg)

    if not rows:
        dt = datetime.strptime(date, "%Y-%m-%d")
        return {
            "report_date": dt.strftime("%A %d %B %Y"),
            "report_date_short": dt.strftime("%a %d %b"),
            "report_date_iso": date,
            "ports_reporting": [],
            "total_species": 0,
            "total_rows": 0,
            "ticker_items": [],
            "prices_by_species": [],
            "comparisons": [],
            "movers": [],
            "highest_price": None,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # --- Group by species ---
    species_map: dict[str, list[dict]] = defaultdict(list)
    ports_seen: set[str] = set()
    species_seen: set[str] = set()
    highest = None

    for r in rows:
        _, port, species, grade, low, high, avg = r
        ports_seen.add(port)
        species_seen.add(species)

        entry = {
            "port": port,
            "grade": grade,
            "price_low": low,
            "price_high": high,
            "price_avg": avg or 0,
            "is_best": False,
        }
        species_map[species].append(entry)

        if avg and (highest is None or avg > highest["price"]):
            highest = {"species": species, "grade": grade, "port": port, "price": avg}

    # Sort each species group by price_avg desc, mark best
    prices_by_species = []
    for species in sorted(species_map.keys()):
        entries = sorted(species_map[species], key=lambda e: e["price_avg"], reverse=True)
        if entries:
            entries[0]["is_best"] = True
        prices_by_species.append({"species": species, "rows": entries})

    # --- Ticker: top price per port ---
    port_best: dict[str, dict] = {}
    for r in rows:
        _, port, species, grade, low, high, avg = r
        if avg and (port not in port_best or avg > port_best[port]["price"]):
            port_best[port] = {
                "port": port,
                "port_code": PORT_CODES.get(port, port[:3].upper()),
                "species": species,
                "price": avg,
            }
    ticker_items = sorted(port_best.values(), key=lambda t: t["price"], reverse=True)

    # --- Cross-port comparisons ---
    # Find species appearing at 2+ ports
    species_ports: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        _, port, species, grade, low, high, avg = r
        if avg:
            # Keep the best price per port per species
            if port not in species_ports[species] or avg > species_ports[species][port]:
                species_ports[species][port] = avg

    multi_port = {
        sp: ports for sp, ports in species_ports.items() if len(ports) >= 2
    }
    # Sort by number of ports desc, then alphabetically
    sorted_comparisons = sorted(
        multi_port.items(), key=lambda x: (-len(x[1]), x[0])
    )

    comparisons = []
    for species, port_prices in sorted_comparisons[:5]:  # Top 5
        max_price = max(port_prices.values())
        ports = sorted(
            [
                {
                    "port": port,
                    "price_avg": price,
                    "bar_width_pct": round((price / max_price) * 100) if max_price else 0,
                }
                for port, price in port_prices.items()
            ],
            key=lambda p: p["price_avg"],
            reverse=True,
        )
        comparisons.append({"species": species, "ports": ports})

    dt = datetime.strptime(date, "%Y-%m-%d")

    return {
        "report_date": dt.strftime("%A %d %B %Y"),
        "report_date_short": dt.strftime("%a %d %b"),
        "report_date_iso": date,
        "ports_reporting": sorted(ports_seen),
        "total_species": len(species_seen),
        "total_rows": len(rows),
        "ticker_items": ticker_items,
        "prices_by_species": prices_by_species,
        "comparisons": comparisons,
        "movers": [],  # Future: day-over-day comparison
        "highest_price": highest,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def generate_report(date: str | None = None) -> Path:
    """Generate the HTML digest report for the given date (or latest).

    Returns the path to the generated HTML file.
    """
    if date is None:
        date = get_latest_date()
        if date is None:
            raise ValueError("No price data in database")

    data = _build_report_data(date)

    env = jinja2.Environment(
        loader=jinja2.PackageLoader("quayside", "templates"),
        autoescape=True,
    )
    template = env.get_template("digest.html")
    html = template.render(**data)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"digest_{date}.html"
    path.write_text(html, encoding="utf-8")

    logger.info("Generated digest: %s (%d species, %d rows)", path, data["total_species"], data["total_rows"])
    return path
