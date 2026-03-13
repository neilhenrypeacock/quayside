"""Generate the daily HTML digest report from SQLite data."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jinja2

from quayside.db import get_all_prices_for_date, get_latest_date, get_previous_date
from quayside.species import normalise_species

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


def _build_movers(date: str, today_rows: list[tuple]) -> list[dict]:
    """Build biggest movers: species with largest day-over-day price change.

    Compares today's best avg price per species (normalised) to the previous
    day's best avg for the same species. Returns up to 6 movers sorted by
    absolute percentage change (mix of risers and fallers).
    """
    prev_date = get_previous_date(date)
    if not prev_date:
        return []

    prev_rows = get_all_prices_for_date(prev_date)
    if not prev_rows:
        return []

    # Skip noisy damaged/mixed items that cause extreme swings
    _NOISE_SUFFIXES = ("dam", "mx", "mixed", "tails", "bru", "link")

    def _is_noisy(raw_species: str) -> bool:
        low = raw_species.lower().strip()
        return any(low.endswith(s) for s in _NOISE_SUFFIXES) or "damaged" in low

    def _best_by_species(rows: list[tuple]) -> dict[str, float]:
        """Best avg price per normalised species across all ports (skip noisy items)."""
        best: dict[str, float] = {}
        for r in rows:
            _, _port, raw_species, _grade, _low, _high, avg = r
            if not avg or _is_noisy(raw_species):
                continue
            species = normalise_species(raw_species)
            if species not in best or avg > best[species]:
                best[species] = avg
        return best

    today_best = _best_by_species(today_rows)
    prev_best = _best_by_species(prev_rows)

    changes = []
    for species, today_price in today_best.items():
        prev_price = prev_best.get(species)
        if not prev_price or prev_price == 0:
            continue
        pct = round(((today_price - prev_price) / prev_price) * 100, 1)
        if abs(pct) < 0.5:
            continue  # Skip negligible changes
        direction = "up" if pct > 0 else "down"
        arrow = "▲" if pct > 0 else "▼"
        sign = "+" if pct > 0 else ""
        changes.append({
            "species": species,
            "price": today_price,
            "price_yesterday": prev_price,
            "change_pct": pct,
            "pct_str": f"{sign}{pct}%",
            "direction": direction,
            "arrow": arrow,
            "label": "Rising" if pct > 0 else "Falling",
            "port": "",  # Cross-port best, no single port
            "grade": f"was £{prev_price:.2f}",
        })

    # Sort by absolute change, take top 6
    changes.sort(key=lambda c: abs(c["change_pct"]), reverse=True)
    return changes[:6]


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
        _, port, raw_species, grade, low, high, avg = r
        species = normalise_species(raw_species)
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
        _, port, raw_species, grade, low, high, avg = r
        species = normalise_species(raw_species)
        if avg and (port not in port_best or avg > port_best[port]["price"]):
            port_best[port] = {
                "port": port,
                "port_code": PORT_CODES.get(port, port[:3].upper()),
                "species": species,
                "price": avg,
            }
    ticker_items = sorted(port_best.values(), key=lambda t: t["price"], reverse=True)

    # --- Cross-port comparisons ---
    # Find species appearing at 2+ ports (using normalised names)
    species_ports: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        _, port, raw_species, grade, low, high, avg = r
        species = normalise_species(raw_species)
        if avg and (port not in species_ports[species] or avg > species_ports[species][port]):
            species_ports[species][port] = avg

    multi_port = {sp: ports for sp, ports in species_ports.items() if len(ports) >= 2}
    # Sort by number of ports desc, then alphabetically
    sorted_comparisons = sorted(multi_port.items(), key=lambda x: (-len(x[1]), x[0]))

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

    # --- Biggest movers (day-over-day) ---
    movers = _build_movers(date, rows)

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
        "movers": movers,
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

    logger.info(
        "Generated digest: %s (%d species, %d rows)",
        path,
        data["total_species"],
        data["total_rows"],
    )
    return path
