"""Generate the daily HTML digest report from SQLite data."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jinja2

from quayside.db import get_30day_species_averages, get_all_prices_for_date, get_latest_date, get_latest_rich_date, get_previous_date, get_total_port_count
from quayside.species import KEY_SPECIES
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

# Noisy/generic species names that produce meaningless price comparisons
_NOISE_WORDS = {"mixed", "offal", "roe", "livers", "frames", "heads", "wings", "skin"}
_NOISE_SUBSTRINGS = ("mixed", "damaged", "bruised", "bru ", " bru", "tails")


def _is_noisy_species(sp: str) -> bool:
    """Return True if this species name is too generic/damaged to be meaningful."""
    low = sp.lower().strip()
    if low in _NOISE_WORDS:
        return True
    return any(n in low for n in _NOISE_SUBSTRINGS)


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

    # Skip noisy damaged/mixed items that cause extreme swings
    _NOISE_SUFFIXES = ("dam", "mx", "mixed", "tails", "bru", "link")

    def _is_noisy(raw_species: str) -> bool:
        low = raw_species.lower().strip()
        return any(low.endswith(s) for s in _NOISE_SUFFIXES) or "damaged" in low

    def _market_avg_by_species(rows: list[tuple]) -> dict[str, float]:
        """Market average price per normalised species across all ports (skip noisy items)."""
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for r in rows:
            _, _port, raw_species, _grade, _low, _high, avg = r
            if not avg or _is_noisy(raw_species):
                continue
            species = normalise_species(raw_species)
            totals[species] = totals.get(species, 0.0) + avg
            counts[species] = counts.get(species, 0) + 1
        return {s: totals[s] / counts[s] for s in totals}

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
    from collections import defaultdict

    # Build per-port candidates: find the species with biggest deviation at each port
    port_best: dict[str, dict] = {}
    port_fallback: dict[str, dict] = {}  # best price if no 30d avg available

    for r in rows:
        _, port, raw_species, grade, low, high, avg = r
        if not avg:
            continue
        species = normalise_species(raw_species)
        if _is_noisy_species(species):
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
        prev_rows = get_all_prices_for_date(prev_date, exclude_demo=True)
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
        if _is_noisy_species(species):
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

    # --- 30-day rolling averages (raw species names, then normalise) ---
    thirty_day_raw = get_30day_species_averages(date)
    # Aggregate raw names → canonical (average of raw averages)
    _thirty_accum: dict[str, list[float]] = defaultdict(list)
    for raw_sp, avg in thirty_day_raw.items():
        _thirty_accum[normalise_species(raw_sp)].append(avg)
    thirty_day_avgs: dict[str, float] = {
        sp: round(sum(vals) / len(vals), 2) for sp, vals in _thirty_accum.items()
    }

    # --- Benchmark snapshot (top commercial species) ---
    benchmark_snapshot = []
    for species in BENCHMARK_SPECIES:
        if species not in species_ports:
            continue
        port_prices = species_ports[species]
        best_price = max(port_prices.values())
        market_avg = round(sum(port_prices.values()) / len(port_prices), 2)

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

        thirty_avg = thirty_day_avgs.get(species)

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

        market_avg_bar_pct = round((market_avg / best_price) * 100) if best_price else 0
        thirty_day_avg_bar_pct = round((thirty_avg / best_price) * 100) if (thirty_avg and best_price) else None

        benchmark_snapshot.append({
            "species": species,
            "best_price": best_price,
            "market_avg": market_avg,
            "thirty_day_avg": thirty_avg,
            "market_avg_bar_pct": market_avg_bar_pct,
            "thirty_day_avg_bar_pct": thirty_day_avg_bar_pct,
            "change": change,
            "ports": ports,
        })

    # --- Ticker: top price per port (skip noisy/generic species) ---
    port_best: dict[str, dict] = {}
    for r in rows:
        _, port, raw_species, grade, low, high, avg = r
        species = normalise_species(raw_species)
        if _is_noisy_species(species):
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
            _, port, raw_species, _grade, _low, _high, avg = r
            if avg:
                key = (port, normalise_species(raw_species))
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
    best_by_species: dict[str, tuple[str, str, float]] = {}  # species → (port, port_code, price)
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
        )

    for sp in KEY_SPECIES:
        if sp not in best_by_species:
            continue
        port_name, port_code, price = best_by_species[sp]
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
