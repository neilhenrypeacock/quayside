"""Generate the daily HTML digest report from SQLite data."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jinja2

from quayside.db import (
    get_30day_port_species_averages,
    get_30day_species_averages,
    get_all_prices_for_date,
    get_latest_rich_date,
    get_previous_date,
    get_total_port_count,
)
from quayside.fx import get_rate
from quayside.ports import get_port_code_map
from quayside.species import KEY_SPECIES, is_noisy_species, normalise_species

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

    prev_rows = get_all_prices_for_date(prev_date, exclude_demo=True)
    if not prev_rows:
        return []

    def _market_avg_by_species(rows: list[tuple]) -> dict[str, float]:
        """Market average price per normalised species (best-per-port, then avg across ports)."""
        # Track best avg per (species, port) — same methodology as trade.py
        best_per_port: dict[str, dict[str, float]] = defaultdict(dict)
        for r in rows:
            _, port, raw_species, _grade, _low, _high, avg, _wkg, _boxes = r
            if not avg:
                continue
            species = normalise_species(raw_species)
            if species is None:
                continue
            existing = best_per_port[species].get(port)
            if existing is None or avg > existing:
                best_per_port[species][port] = avg
        return {
            sp: sum(ports.values()) / len(ports)
            for sp, ports in best_per_port.items()
        }

    today_best = _market_avg_by_species(today_rows)
    prev_best = _market_avg_by_species(prev_rows)

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


def _build_market_summary(
    movers: list[dict],
    species_ports: dict[str, dict[str, float]],
    prev_best: dict[str, float],
    highest: dict | None,
    ports_seen: set[str],
    species_seen: set[str],
) -> list[str]:
    """Generate 2–3 plain-English lines summarising today's market holistically."""
    lines = []

    risers = [m for m in movers if m["direction"] == "up"]
    fallers = [m for m in movers if m["direction"] == "down"]
    if risers and fallers:
        lines.append(f"Prices are mixed today \u2014 {len(risers)} species firmer, {len(fallers)} lower vs yesterday.")
    elif risers:
        lines.append(f"Prices broadly firmer today with {len(risers)} species rising vs yesterday.")
    elif fallers:
        lines.append(f"Prices under pressure \u2014 {len(fallers)} species lower vs yesterday.")
    else:
        lines.append("Prices broadly stable today across UK ports.")

    if movers:
        top = movers[0]
        lines.append(f"{top['species']} is the standout {top['label'].lower()} at \u00a3{top['price']:.2f}/kg ({top['pct_str']} vs yesterday).")
    elif highest:
        lines.append(f"{highest['species']} fetched the highest price today at \u00a3{highest['price']:.2f}/kg ({highest['port']}).")

    port_count = len(ports_seen)
    species_count = len(species_seen)
    lines.append(f"{port_count} port{'s' if port_count != 1 else ''} reporting today with {species_count} species on offer.")

    return lines


def _build_port_highlights(rows: list[tuple], thirty_day_raw: dict[str, float]) -> list[dict]:
    """Per-port highlight: species with biggest % deviation from its 30-day average today.

    Falls back to best price if no 30-day data is available for any species at that port.
    """

    # Build per-port candidates: find the species with biggest deviation at each port
    port_best: dict[str, dict] = {}
    port_fallback: dict[str, dict] = {}  # best price if no 30d avg available

    for r in rows:
        _, port, raw_species, grade, low, high, avg, _wkg, _boxes = r
        if not avg:
            continue
        species = normalise_species(raw_species)
        if species is None or is_noisy_species(species):
            continue

        # Track fallback (highest price per port)
        if port not in port_fallback or avg > port_fallback[port]["price"]:
            port_fallback[port] = {"port": port, "species": species, "price": avg, "has_deviation": False}

        thirty_avg = thirty_day_raw.get(raw_species)
        if not thirty_avg or thirty_avg == 0:
            continue

        pct = ((avg - thirty_avg) / thirty_avg) * 100
        if port not in port_best or abs(pct) > abs(port_best[port]["pct"]):
            direction = "up" if pct > 0 else "down"
            sign = "+" if pct > 0 else ""
            port_best[port] = {
                "port": port,
                "species": species,
                "price": avg,
                "thirty_avg": thirty_avg,
                "pct": pct,
                "pct_str": f"{sign}{round(pct)}%",
                "direction": direction,
                "arrow": "▲" if pct > 0 else "▼",
                "has_deviation": True,
            }

    result = []
    for port in sorted(port_best.keys() | port_fallback.keys()):
        result.append(port_best.get(port) or port_fallback[port])
    return result


def build_report_data(date: str) -> dict:
    """Query DB and assemble template context for the given date."""
    rows = get_all_prices_for_date(date, exclude_demo=True)  # (date, port, species, grade, low, high, avg)

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
            "port_highlights": [],
            "prices_by_species": [],
            "benchmark_snapshot": [],
            "key_species_summary": [],
            "movers": [],
            "market_summary": [],
            "total_ports": get_total_port_count(),
            "best_value_port": None,
            "biggest_spread": None,
            "highest_price": None,
            "fx_rate": None,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # --- Group by species + track ports per species ---
    species_map: dict[str, list[dict]] = defaultdict(list)
    species_ports: dict[str, dict[str, float]] = defaultdict(dict)
    # Tracks full record details for the best-avg row per (species, port)
    species_port_details: dict[str, dict[str, dict]] = defaultdict(dict)
    ports_seen: set[str] = set()
    species_seen: set[str] = set()
    highest = None

    for r in rows:
        _, port, raw_species, grade, low, high, avg, weight_kg, boxes = r
        species = normalise_species(raw_species)
        if species is None:
            continue  # noise-filtered species
        ports_seen.add(port)
        species_seen.add(species)

        entry = {
            "port": port,
            "grade": grade,
            "price_low": low,
            "price_high": high,
            "price_avg": avg or 0,
            "weight_kg": weight_kg,
            "boxes": boxes,
            "is_best": False,
        }
        species_map[species].append(entry)

        # Best price per species per port (for cross-port + tiering)
        if avg and (port not in species_ports[species] or avg > species_ports[species][port]):
            species_ports[species][port] = avg
            species_port_details[species][port] = {
                "price_low": low,
                "price_high": high,
                "weight_kg": weight_kg,
                "boxes": boxes,
            }

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
        prev_rows = get_all_prices_for_date(prev_date, exclude_demo=True)
        if prev_rows:
            for r in prev_rows:
                _, _port, raw_species, _grade, _low, _high, avg, _wkg, _boxes = r
                if not avg:
                    continue
                sp = normalise_species(raw_species)
                if sp is None:
                    continue
                if sp not in prev_best or avg > prev_best[sp]:
                    prev_best[sp] = avg

    key_species_summary = []
    for species in multi_port_species:
        if is_noisy_species(species):
            continue
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

        market_avg = round(sum(port_prices.values()) / len(port_prices), 2)

        key_species_summary.append({
            "species": species,
            "best_price": best_price,
            "market_avg": market_avg,
            "best_port": best_port,
            "best_port_code": PORT_CODES.get(best_port, best_port[:3].upper()),
            "port_count": port_count,
            "change": change,
        })

    # Sort: port count desc, then best price desc
    key_species_summary.sort(key=lambda s: (-s["port_count"], -s["best_price"]))

    # --- 30-day rolling averages: per-port (for bar markers) ---
    thirty_day_raw = get_30day_species_averages(date)
    port_thirty_day_raw = get_30day_port_species_averages(date)

    # Build canonical-keyed lookup: {(port, canonical_species): (avg, trade_days)}
    # Multiple raw names can map to the same canonical — use weighted average by trade days.
    _port_thirty_accum: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    for (port, raw_sp), (avg, trade_days) in port_thirty_day_raw.items():
        sp = normalise_species(raw_sp)
        if sp is not None:
            _port_thirty_accum[(port, sp)].append((avg, trade_days))
    port_thirty_day: dict[tuple[str, str], tuple[float, int]] = {}
    for (port, sp), vals in _port_thirty_accum.items():
        total_days = sum(c for _, c in vals)
        weighted_avg = sum(a * c for a, c in vals) / total_days if total_days else 0
        port_thirty_day[(port, sp)] = (round(weighted_avg, 2), total_days)

    _MIN_TRADE_DAYS = 5  # minimum sessions before showing a 30d avg marker

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

        # Collect per-port 30d avgs (only those with sufficient history)
        port_30d_avgs: dict[str, float] = {}
        for port in port_prices:
            lookup = port_thirty_day.get((port, species))
            if lookup and lookup[1] >= _MIN_TRADE_DAYS:
                port_30d_avgs[port] = lookup[0]

        # Scale: accommodate any 30d avg that exceeds today's best price
        scale = max(best_price, max(port_30d_avgs.values())) if port_30d_avgs else best_price

        # Per-port breakdown with bar widths
        ports = []
        for port, price in port_prices.items():
            details = species_port_details[species].get(port, {})
            port_low = details.get("price_low")
            port_high = details.get("price_high")
            port_wkg = details.get("weight_kg")
            port_boxes = details.get("boxes")

            # Detect synthetic midpoint (range bar): price_low/high present, no weight,
            # and price_avg equals the (low+high)/2 midpoint — e.g. Scrabster
            is_range_bar = (
                port_low is not None and port_high is not None
                and port_wkg is None
                and port_low != port_high
                and abs(price - (port_low + port_high) / 2) < 0.01
            )
            bar_low_pct = round((port_low / scale) * 100) if (is_range_bar and scale) else 0
            bar_high_pct = round((port_high / scale) * 100) if (is_range_bar and scale) else 0

            thirty_avg_port = port_30d_avgs.get(port)
            thirty_day_avg_pct = round((thirty_avg_port / scale) * 100) if (thirty_avg_port and scale) else None

            ports.append({
                "port": port,
                "price_avg": price,
                "bar_width_pct": round((price / scale) * 100) if scale else 0,
                "price_low": port_low,
                "price_high": port_high,
                "weight_kg": port_wkg,
                "boxes": port_boxes,
                "is_range_bar": is_range_bar,
                "bar_low_pct": bar_low_pct,
                "bar_range_width_pct": bar_high_pct - bar_low_pct,
                "thirty_day_avg": thirty_avg_port,
                "thirty_day_avg_pct": thirty_day_avg_pct,
            })
        ports.sort(key=lambda p: p["price_avg"], reverse=True)

        benchmark_snapshot.append({
            "species": species,
            "best_price": best_price,
            "change": change,
            "ports": ports,
        })

    # --- Ticker: top price per port (skip noisy/generic species) ---
    port_best: dict[str, dict] = {}
    for r in rows:
        _, port, raw_species, grade, low, high, avg, _wkg, _boxes = r
        species = normalise_species(raw_species)
        if species is None or is_noisy_species(species):
            continue
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

    # --- Port highlights (biggest % deviation from 30-day avg per port) ---
    port_highlights = _build_port_highlights(rows, thirty_day_raw)

    # --- Market summary (holistic 2–3 sentence overview) ---
    market_summary = _build_market_summary(movers, species_ports, prev_best, highest, ports_seen, species_seen)

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
        "port_highlights": port_highlights,
        "prices_by_species": prices_by_species,
        "benchmark_snapshot": benchmark_snapshot,
        "key_species_summary": key_species_summary,
        "movers": movers,
        "market_summary": market_summary,
        "total_ports": get_total_port_count(),
        "best_value_port": None,
        "biggest_spread": None,
        "highest_price": highest,
        "fx_rate": fx_data,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def build_landing_data(date: str) -> dict:
    """Build the minimal data set needed by the landing page hero section.

    Computes per-port Haddock prices with individual day-over-day % changes
    (build_report_data only gives the cross-port best, not per-port splits),
    plus top-mover highlight data and stats for the mock digest panel.
    """
    data = build_report_data(date)

    # --- Load previous day's prices once (used for both haddock rows + ticker) ---
    prev_date = get_previous_date(date)
    # Best price per (port, canonical_species) on the previous day
    prev_port_species: dict[tuple[str, str], float] = {}
    if prev_date:
        prev_rows = get_all_prices_for_date(prev_date, exclude_demo=True)
        for r in prev_rows:
            _, port, raw_species, _grade, _low, _high, avg, _wkg, _boxes = r
            if avg:
                _sp = normalise_species(raw_species)
                if _sp is None:
                    continue
                key = (port, _sp)
                if key not in prev_port_species or avg > prev_port_species[key]:
                    prev_port_species[key] = avg

    # Convenience: per-port previous best for Haddock specifically
    prev_port_haddock = {
        port: price
        for (port, species), price in prev_port_species.items()
        if species == "Haddock"
    }

    haddock_rows = []
    for item in data["prices_by_species"]:
        if item["species"] == "Haddock":
            for entry in item["rows"]:
                port = entry["port"]
                price = entry["price_avg"]
                grade = entry["grade"] or ""
                prev = prev_port_haddock.get(port)

                direction, pct_str, arrow = "flat", "—", "—"
                if prev and prev > 0:
                    pct = round(((price - prev) / prev) * 100)
                    direction = "up" if pct > 0 else ("down" if pct < 0 else "flat")
                    sign = "+" if pct > 0 else ""
                    pct_str = f"{sign}{pct}%"
                    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")

                haddock_rows.append({
                    "port_label": f"{port} · {grade}" if grade else port,
                    "price": price,
                    "pct_str": pct_str,
                    "direction": direction,
                    "arrow": arrow,
                })
            break

    haddock_rows.sort(key=lambda r: r["price"], reverse=True)

    # --- Top movers with port attribution ---
    # movers have no port field; find which port carries the best price today
    species_top_port: dict[str, tuple[str, float]] = {}
    for item in data["prices_by_species"]:
        if item["rows"]:
            best = item["rows"][0]  # already sorted price desc
            species_top_port[item["species"]] = (best["port"], best["price_avg"])

    top_movers = []
    for m in data["movers"][:3]:
        port, price = species_top_port.get(m["species"], ("", m["price"]))
        top_movers.append({
            "species": m["species"],
            "price": price,
            "port": port,
            "pct_str": m["pct_str"],
            "direction": m["direction"],
        })

    # --- Ticker items with per-port day-over-day direction ---
    ticker_items = []
    for item in data["ticker_items"]:
        prev = prev_port_species.get((item["port"], item["species"]))
        if prev and prev > 0:
            pct = (item["price"] - prev) / prev * 100
            direction = "up" if pct > 0.5 else ("down" if pct < -0.5 else "flat")
        else:
            direction = "flat"
        ticker_items.append({**item, "direction": direction})

    fx_str = None
    if data["fx_rate"] and data["fx_rate"].get("rate"):
        fx_str = f"GBP/EUR {data['fx_rate']['rate']:.2f}"

    # --- Key species rows for mock card (one row per species, no grade duplication) ---
    # Prefer key_species_summary (multi-port); fall back to best single-port price.
    key_species_set = set(KEY_SPECIES)
    key_species_rows = []

    # Build best-price-per-species lookup from all today's prices (single source of truth)
    best_by_species: dict[str, tuple[str, str, float, float | None, int | None]] = {}
    for item in data["prices_by_species"]:
        sp = item["species"]
        if sp not in key_species_set or not item["rows"]:
            continue
        best_row = item["rows"][0]  # already sorted price desc
        port_name = best_row["port"]
        best_by_species[sp] = (
            port_name,
            PORT_CODES.get(port_name, port_name[:3].upper()),
            best_row["price_avg"],
            best_row.get("weight_kg"),
            best_row.get("boxes"),
        )

    for sp in KEY_SPECIES:
        if sp not in best_by_species:
            continue
        port_name, port_code, price, weight_kg, boxes = best_by_species[sp]
        prev = prev_port_species.get((port_name, sp))
        direction, pct_str = "flat", "—"
        if prev and prev > 0:
            pct = round(((price - prev) / prev) * 100)
            direction = "up" if pct > 0 else ("down" if pct < 0 else "flat")
            sign = "+" if pct > 0 else ""
            pct_str = f"{sign}{pct}%"
        key_species_rows.append({
            "species": sp,
            "port": port_code,
            "price": price,
            "direction": direction,
            "pct_str": pct_str,
            "weight_kg": weight_kg,
            "boxes": boxes,
        })
        if len(key_species_rows) >= 6:
            break

    return {
        "date_upper": data["report_date_short"].upper(),
        "port_count": len(data["ports_reporting"]),
        "species_count": data["total_species"],
        "price_count": data["total_rows"],
        "haddock_rows": haddock_rows[:5],
        "key_species_rows": key_species_rows,
        "ticker_items": ticker_items,
        "top_movers": top_movers,
        "fx_str": fx_str,
    }


def generate_report(date: str | None = None) -> Path:
    """Generate the HTML digest report for the given date (or latest).

    Returns the path to the generated HTML file.
    """
    if date is None:
        date = get_latest_rich_date()
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
