"""Generate the daily HTML digest report from SQLite data."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jinja2

from quayside.db import get_all_prices_for_date, get_latest_date, get_previous_date
from quayside.fx import get_rate
from quayside.ports import get_port_code_map
from quayside.species import normalise_species

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _get_port_codes() -> dict[str, str]:
    """Load port codes dynamically, with hardcoded fallback."""
    codes = get_port_code_map()
    if codes:
        return codes
    # Fallback if ports table not yet seeded
    return {
        "Peterhead": "PTH", "Brixham": "BRX", "Scrabster": "SCR",
        "Newlyn": "NLN", "Lerwick": "LWK", "Fraserburgh": "FRB",
        "Kinlochbervie": "KLB",
    }


PORT_CODES = _get_port_codes()

# Benchmark species shown in the market snapshot — ordered by commercial importance
BENCHMARK_SPECIES = [
    "Haddock", "Cod", "Monkfish", "Hake", "Dover Sole",
    "Turbot", "Plaice", "Lemon Sole", "Brill", "Coley (Saithe)",
]


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


def build_report_data(date: str) -> dict:
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
            "benchmark_snapshot": [],
            "key_species_summary": [],
            "movers": [],
            "best_value_port": None,
            "biggest_spread": None,
            "highest_price": None,
            "fx_rate": None,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # --- Group by species + track ports per species ---
    species_map: dict[str, list[dict]] = defaultdict(list)
    species_ports: dict[str, dict[str, float]] = defaultdict(dict)
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

        # Best price per species per port (for cross-port + tiering)
        if avg and (port not in species_ports[species] or avg > species_ports[species][port]):
            species_ports[species][port] = avg

        if avg and (highest is None or avg > highest["price"]):
            highest = {"species": species, "grade": grade, "port": port, "price": avg}

    # Sort each species group by price_avg desc, mark best
    prices_by_species = []
    for species in sorted(species_map.keys()):
        entries = sorted(species_map[species], key=lambda e: e["price_avg"], reverse=True)
        if entries:
            entries[0]["is_best"] = True
        prices_by_species.append({"species": species, "rows": entries})

    # --- Key species summary (one row per multi-port species) ---
    multi_port_species = {sp for sp, ports in species_ports.items() if len(ports) >= 2}
    # Get previous day's best prices for day-over-day change
    prev_date = get_previous_date(date)
    prev_best: dict[str, float] = {}
    if prev_date:
        prev_rows = get_all_prices_for_date(prev_date)
        if prev_rows:
            for r in prev_rows:
                _, _port, raw_species, _grade, _low, _high, avg = r
                if not avg:
                    continue
                sp = normalise_species(raw_species)
                if sp not in prev_best or avg > prev_best[sp]:
                    prev_best[sp] = avg

    key_species_summary = []
    for species in multi_port_species:
        port_prices = species_ports[species]
        best_port = max(port_prices, key=port_prices.get)
        best_price = port_prices[best_port]
        port_count = len(port_prices)

        # Day-over-day change
        prev_price = prev_best.get(species)
        change = {}
        if prev_price and prev_price > 0:
            pct = round(((best_price - prev_price) / prev_price) * 100, 1)
            if abs(pct) >= 0.5:
                sign = "+" if pct > 0 else ""
                change = {
                    "pct": pct,
                    "pct_str": f"{sign}{pct}%",
                    "arrow": "▲" if pct > 0 else "▼",
                    "direction": "up" if pct > 0 else "down",
                }

        key_species_summary.append({
            "species": species,
            "best_price": best_price,
            "best_port": best_port,
            "best_port_code": PORT_CODES.get(best_port, best_port[:3].upper()),
            "port_count": port_count,
            "change": change,
        })

    # Sort: port count desc, then best price desc
    key_species_summary.sort(key=lambda s: (-s["port_count"], -s["best_price"]))

    # --- Benchmark snapshot (top commercial species) ---
    benchmark_snapshot = []
    for species in BENCHMARK_SPECIES:
        if species not in species_ports:
            continue
        port_prices = species_ports[species]
        best_price = max(port_prices.values())

        prev_price = prev_best.get(species)
        change = {}
        if prev_price and prev_price > 0:
            pct = round(((best_price - prev_price) / prev_price) * 100, 1)
            if abs(pct) >= 0.5:
                sign = "+" if pct > 0 else ""
                change = {
                    "pct": pct,
                    "pct_str": f"{sign}{pct}%",
                    "arrow": "▲" if pct > 0 else "▼",
                    "direction": "up" if pct > 0 else "down",
                }

        # Per-port breakdown with bar widths (same pattern as cross-port comparisons)
        ports = sorted(
            [
                {
                    "port": port,
                    "price_avg": price,
                    "bar_width_pct": round((price / best_price) * 100) if best_price else 0,
                }
                for port, price in port_prices.items()
            ],
            key=lambda p: p["price_avg"],
            reverse=True,
        )

        benchmark_snapshot.append({
            "species": species,
            "best_price": best_price,
            "change": change,
            "ports": ports,
        })

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

    # --- Biggest movers (day-over-day) ---
    movers = _build_movers(date, rows)

    # --- Today's Highlights ---
    # Best value port: port with lowest average of best-grade prices across species
    port_all_prices: dict[str, list[float]] = defaultdict(list)
    for _sp, port_prices in species_ports.items():
        for port, price in port_prices.items():
            port_all_prices[port].append(price)

    best_value_port = None
    if port_all_prices:
        port_avgs = {
            port: sum(prices) / len(prices)
            for port, prices in port_all_prices.items()
        }
        bv_port = min(port_avgs, key=port_avgs.get)
        # Grab 3 example species at this port (cheapest first)
        bv_examples = []
        for sp, port_prices in sorted(species_ports.items()):
            if bv_port in port_prices:
                bv_examples.append({"species": sp, "price": port_prices[bv_port]})
        bv_examples.sort(key=lambda e: e["price"])
        best_value_port = {
            "port": bv_port,
            "avg_price": round(port_avgs[bv_port], 2),
            "examples": bv_examples[:3],
        }

    # Biggest cross-port spread: species with largest % gap between highest and lowest port
    biggest_spread = None
    multi_port_map = {sp: ports for sp, ports in species_ports.items() if len(ports) >= 2}
    best_spread_pct = 0
    for sp, port_prices in multi_port_map.items():
        max_p = max(port_prices.values())
        min_p = min(port_prices.values())
        if min_p > 0:
            spread_pct = round(((max_p - min_p) / min_p) * 100, 1)
            if spread_pct > best_spread_pct:
                best_spread_pct = spread_pct
                max_port = max(port_prices, key=port_prices.get)
                min_port = min(port_prices, key=port_prices.get)
                spread_ports = sorted(
                    [{"port": p, "price": pr} for p, pr in port_prices.items()],
                    key=lambda x: x["price"],
                    reverse=True,
                )
                biggest_spread = {
                    "species": sp,
                    "spread_pct": spread_pct,
                    "high_port": max_port,
                    "low_port": min_port,
                    "ports": spread_ports,
                }

    dt = datetime.strptime(date, "%Y-%m-%d")

    # --- Exchange rate (GBP → EUR) ---
    fx_data = get_rate(base="GBP", target="EUR", date=date)

    return {
        "report_date": dt.strftime("%A %d %B %Y"),
        "report_date_short": dt.strftime("%a %d %b"),
        "report_date_iso": date,
        "ports_reporting": sorted(ports_seen),
        "total_species": len(species_seen),
        "total_rows": len(rows),
        "ticker_items": ticker_items,
        "prices_by_species": prices_by_species,
        "benchmark_snapshot": benchmark_snapshot,
        "key_species_summary": key_species_summary,
        "movers": movers,
        "best_value_port": best_value_port,
        "biggest_spread": biggest_spread,
        "highest_price": highest,
        "fx_rate": fx_data,
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

    data = build_report_data(date)

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
