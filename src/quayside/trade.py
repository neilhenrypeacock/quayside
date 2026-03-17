"""Build data for the premium Trade Dashboard.

The trade dashboard is a species-first intelligence tool for fish merchants:
where to buy each species today, whether today's price is good or bad
relative to recent history, and where the cross-port arbitrage opportunities are.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from quayside.db import (
    get_30day_species_averages,
    get_all_ports,
    get_all_prices_for_date,
    get_market_averages_for_range,
    get_previous_date,
    get_prices_for_date_range,
    get_trading_dates,
    get_trading_dates_recent,
)
from quayside.ports import get_port_code_map
from quayside.review import sparkline_svg
from quayside.species import (
    get_species_category,
    is_noisy_species,
    normalise_species,
)


def _port_codes() -> dict[str, str]:
    codes = get_port_code_map()
    if codes:
        return codes
    return {
        "Peterhead": "PTH", "Brixham": "BRX", "Scrabster": "SCR",
        "Newlyn": "NLN", "Lerwick": "LWK", "Fraserburgh": "FRB",
    }


def _best_price_per_port(rows: list[tuple]) -> dict[str, dict[str, float]]:
    """Build {canonical_species: {port: best_avg}} from price rows."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for _date, port, raw_species, _grade, _low, _high, avg in rows:
        if avg is None:
            continue
        canonical = normalise_species(raw_species)
        existing = out[canonical].get(port)
        if existing is None or avg > existing:
            out[canonical][port] = avg
    return dict(out)


def build_trade_data(date: str) -> dict:
    """Assemble all data for the Trade Dashboard for the given date."""
    # ── Raw data ──────────────────────────────────────────────────────────────
    rows = get_all_prices_for_date(date, exclude_demo=True)
    prev_date = get_previous_date(date)
    prev_rows = get_all_prices_for_date(prev_date, exclude_demo=True) if prev_date else []

    # 30-day rolling averages (raw species names)
    thirty_day_raw = get_30day_species_averages(date)
    # Normalise raw 30d avgs to canonical names
    _thirty_accum: dict[str, list[float]] = defaultdict(list)
    for raw_sp, avg in thirty_day_raw.items():
        _thirty_accum[normalise_species(raw_sp)].append(avg)
    thirty_day_avgs: dict[str, float] = {
        sp: round(sum(vals) / len(vals), 2) for sp, vals in _thirty_accum.items()
    }

    # 90-day history for charts
    dt = datetime.strptime(date, "%Y-%m-%d")
    start_90d = (dt - timedelta(days=130)).strftime("%Y-%m-%d")  # ~90 trading days
    rows_90d = get_prices_for_date_range(start_90d, date)
    trading_dates_90d = get_trading_dates(start_90d, date)

    # 7-day market averages for momentum sparklines
    start_7d = (dt - timedelta(days=14)).strftime("%Y-%m-%d")
    market_avgs_7d = get_market_averages_for_range(start_7d, date)
    trading_dates_7d = get_trading_dates(start_7d, date)

    port_code_map = _port_codes()
    active_ports = get_all_ports(status="active")
    active_port_names = [p["name"] for p in active_ports]

    # ── Build species → {port: price} matrix ─────────────────────────────────
    today_matrix = _best_price_per_port(rows)
    prev_matrix = _best_price_per_port(prev_rows)

    # Ordered list of ports that appear in today's data (or active ports)
    ports_today: set[str] = set()
    for port_prices in today_matrix.values():
        ports_today.update(port_prices.keys())
    all_ports_list = sorted(ports_today)

    # ── Build matrix rows ─────────────────────────────────────────────────────
    matrix: list[dict] = []
    for species, port_prices in sorted(today_matrix.items()):
        if is_noisy_species(species):
            continue
        prices = list(port_prices.values())
        market_avg = round(sum(prices) / len(prices), 2)
        market_min = min(prices)
        market_max = max(prices)

        thirty_avg = thirty_day_avgs.get(species)
        vs_30d_pct: float | None = None
        vs_30d_direction = "flat"
        if thirty_avg and thirty_avg > 0:
            vs_30d_pct = round((market_avg - thirty_avg) / thirty_avg * 100, 1)
            vs_30d_direction = "up" if vs_30d_pct > 0 else ("down" if vs_30d_pct < 0 else "flat")

        prev_prices = list(prev_matrix.get(species, {}).values())
        vs_yesterday_pct: float | None = None
        vs_yesterday_direction = "flat"
        if prev_prices:
            prev_market_avg = sum(prev_prices) / len(prev_prices)
            if prev_market_avg > 0:
                vs_yesterday_pct = round((market_avg - prev_market_avg) / prev_market_avg * 100, 1)
                vs_yesterday_direction = "up" if vs_yesterday_pct > 0 else ("down" if vs_yesterday_pct < 0 else "flat")

        spread_pct: float | None = None
        if len(prices) >= 2 and market_min > 0:
            spread_pct = round((market_max - market_min) / market_min * 100, 1)

        best_buy_port = min(port_prices, key=port_prices.get)

        matrix.append({
            "species": species,
            "category": get_species_category(species),
            "ports": dict(port_prices),
            "market_avg": market_avg,
            "market_min": market_min,
            "market_max": market_max,
            "thirty_day_avg": thirty_avg,
            "vs_30d_pct": vs_30d_pct,
            "vs_30d_direction": vs_30d_direction,
            "vs_yesterday_pct": vs_yesterday_pct,
            "vs_yesterday_direction": vs_yesterday_direction,
            "spread_pct": spread_pct,
            "best_buy_port": best_buy_port,
            "best_buy_price": port_prices[best_buy_port],
        })

    # Sort default: by spread desc (most arbitrage opportunity first)
    matrix.sort(key=lambda r: r["spread_pct"] or 0, reverse=True)

    # ── Arbitrage opportunities ───────────────────────────────────────────────
    arbitrage = []
    for row in matrix:
        if row["spread_pct"] is None or len(row["ports"]) < 2:
            continue
        low_port = row["best_buy_port"]
        low_price = row["market_min"]
        high_port = max(row["ports"], key=row["ports"].get)
        high_price = row["market_max"]
        arbitrage.append({
            "species": row["species"],
            "low_port": low_port,
            "low_price": low_price,
            "high_port": high_port,
            "high_price": high_price,
            "spread_gbp": round(high_price - low_price, 2),
            "spread_pct": row["spread_pct"],
        })
    arbitrage.sort(key=lambda a: a["spread_pct"], reverse=True)
    arbitrage = arbitrage[:5]

    # ── Market momentum (7-day sparklines) ───────────────────────────────────
    # {canonical: [price_per_trading_day]} — market avg per canonical species per day
    species_7d: dict[str, list[float | None]] = {}
    canonical_names = {row["species"] for row in matrix}
    for sp in canonical_names:
        series: list[float | None] = []
        for d in trading_dates_7d:
            day_data = market_avgs_7d.get(d, {})
            # market_avgs_7d returns {raw_species: avg} per date — normalise
            day_by_canonical: dict[str, list[float]] = defaultdict(list)
            for raw_sp, avg in day_data.items():
                can = normalise_species(raw_sp)
                day_by_canonical[can].append(avg)
            if sp in day_by_canonical:
                series.append(round(sum(day_by_canonical[sp]) / len(day_by_canonical[sp]), 2))
            else:
                series.append(None)
        species_7d[sp] = series

    momentum_candidates = []
    for sp, series in species_7d.items():
        nums = [v for v in series if v is not None]
        if len(nums) < 3:
            continue
        first, last = nums[0], nums[-1]
        if first == 0:
            continue
        trend_pct = round((last - first) / first * 100, 1)
        if abs(trend_pct) < 1.0:
            continue
        momentum_candidates.append({
            "species": sp,
            "current_price": last,
            "trend_pct": trend_pct,
            "direction": "up" if trend_pct > 0 else "down",
            "sparkline_svg": sparkline_svg(series, width=60, height=20),
        })

    momentum_candidates.sort(key=lambda m: abs(m["trend_pct"]), reverse=True)
    risers = [m for m in momentum_candidates if m["direction"] == "up"][:3]
    fallers = [m for m in momentum_candidates if m["direction"] == "down"][:3]

    # ── Market pulse KPIs ─────────────────────────────────────────────────────
    ports_reporting = len(ports_today)
    ports_total = max(len(active_port_names), ports_reporting)
    species_tracked = len(matrix)

    # Overall market direction: avg of vs_yesterday_pct across all species with data
    direction_vals = [r["vs_yesterday_pct"] for r in matrix if r["vs_yesterday_pct"] is not None]
    market_direction_pct = round(sum(direction_vals) / len(direction_vals), 1) if direction_vals else None
    market_direction_label = "up" if (market_direction_pct and market_direction_pct > 0) else ("down" if (market_direction_pct and market_direction_pct < 0) else "flat")
    market_direction_arrow = "▲" if market_direction_label == "up" else ("▼" if market_direction_label == "down" else "—")

    # Best value port: lowest avg price across all species today
    port_all_avgs: dict[str, list[float]] = defaultdict(list)
    for row in matrix:
        for port, price in row["ports"].items():
            port_all_avgs[port].append(price)
    best_value_port = None
    best_value_port_avg = None
    if port_all_avgs:
        port_means = {p: sum(vals) / len(vals) for p, vals in port_all_avgs.items()}
        best_value_port = min(port_means, key=port_means.get)
        best_value_port_avg = round(port_means[best_value_port], 2)

    # Biggest mover (vs yesterday)
    biggest_mover: dict | None = None
    biggest_mover_abs = 0.0
    for row in matrix:
        if row["vs_yesterday_pct"] is not None and abs(row["vs_yesterday_pct"]) > biggest_mover_abs:
            biggest_mover_abs = abs(row["vs_yesterday_pct"])
            biggest_mover = row

    # Widest spread today
    widest_spread: dict | None = None
    widest_spread_pct = 0.0
    for row in matrix:
        if row["spread_pct"] is not None and row["spread_pct"] > widest_spread_pct:
            widest_spread_pct = row["spread_pct"]
            widest_spread = row

    pulse = {
        "ports_reporting": ports_reporting,
        "ports_total": ports_total,
        "species_tracked": species_tracked,
        "market_direction_pct": market_direction_pct,
        "market_direction_label": market_direction_label,
        "market_direction_arrow": market_direction_arrow,
        "best_value_port": best_value_port,
        "best_value_port_avg": best_value_port_avg,
        "biggest_mover_species": biggest_mover["species"] if biggest_mover else None,
        "biggest_mover_pct": biggest_mover["vs_yesterday_pct"] if biggest_mover else None,
        "biggest_mover_direction": biggest_mover["vs_yesterday_direction"] if biggest_mover else "flat",
        "widest_spread_species": widest_spread["species"] if widest_spread else None,
        "widest_spread_pct": widest_spread["spread_pct"] if widest_spread else None,
        "widest_spread_low_port": widest_spread["best_buy_port"] if widest_spread else None,
        "widest_spread_high_port": max(widest_spread["ports"], key=widest_spread["ports"].get) if widest_spread else None,
    }

    # ── Port status strip ─────────────────────────────────────────────────────
    port_species_count: dict[str, int] = defaultdict(int)
    for row in matrix:
        for port in row["ports"]:
            port_species_count[port] += 1

    # Include all active ports, even those not reporting today
    status_ports = sorted(set(active_port_names) | ports_today)
    port_status = []
    for port in status_ports:
        reporting = port in ports_today
        port_status.append({
            "port": port,
            "code": port_code_map.get(port, port[:3].upper()),
            "reporting": reporting,
            "species_count": port_species_count.get(port, 0),
        })

    # ── 90-day chart data ─────────────────────────────────────────────────────
    # {canonical_species: {port: {date: best_avg}}}
    chart_raw: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for d, port, raw_sp, _grade, _low, _high, avg in rows_90d:
        if avg is None:
            continue
        canonical = normalise_species(raw_sp)
        if canonical not in canonical_names:
            continue
        existing = chart_raw[canonical][port].get(d)
        if existing is None or avg > existing:
            chart_raw[canonical][port][d] = avg

    # Also build market_avg per date per canonical species
    chart_market: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for d, _port, raw_sp, _grade, _low, _high, avg in rows_90d:
        if avg is None:
            continue
        canonical = normalise_species(raw_sp)
        if canonical not in canonical_names:
            continue
        chart_market[canonical][d].append(avg)

    chart_data: dict[str, dict] = {}
    for sp in canonical_names:
        port_series: dict[str, list[float | None]] = {}
        for port in all_ports_list:
            if port in chart_raw.get(sp, {}):
                port_series[port] = [chart_raw[sp][port].get(d) for d in trading_dates_90d]
        market_avg_series = [
            round(sum(chart_market[sp][d]) / len(chart_market[sp][d]), 2)
            if chart_market[sp].get(d) else None
            for d in trading_dates_90d
        ]
        chart_data[sp] = {
            "labels": trading_dates_90d,
            "ports": port_series,
            "market_avg": market_avg_series,
            "thirty_day_avg": thirty_day_avgs.get(sp),
        }

    # ── Date/display helpers ──────────────────────────────────────────────────
    dt_display = datetime.strptime(date, "%Y-%m-%d")
    date_display = dt_display.strftime("%A %d %B %Y")
    date_display_short = dt_display.strftime("%a %d %b")
    ninety_days_ago = (dt - timedelta(days=90)).strftime("%Y-%m-%d")
    recent_dates = get_trading_dates_recent(15)

    return {
        "date": date,
        "date_display": date_display,
        "date_display_short": date_display_short,
        "recent_dates": recent_dates,
        "all_ports": all_ports_list,
        "port_codes": port_code_map,
        "categories": ["all", "demersal", "flatfish", "shellfish", "pelagic", "other"],
        "pulse": pulse,
        "port_status": port_status,
        "matrix": matrix,
        "arbitrage": arbitrage,
        "momentum": {"risers": risers, "fallers": fallers},
        "chart_data": chart_data,
        "ninety_days_ago": ninety_days_ago,
        "generated_at": datetime.now().strftime("%H:%M"),
    }
