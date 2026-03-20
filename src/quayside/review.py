"""Build data for weekly and monthly review pages."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from quayside.db import (
    get_latest_date,
    get_prices_for_date_range,
    get_trading_dates,
)
from quayside.report import BENCHMARK_SPECIES, PORT_CODES
from quayside.species import normalise_species

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _best_price_per_species_per_date(
    rows: list[tuple],
) -> dict[str, dict[str, float]]:
    """Build {species: {date: best_avg}} from price rows.

    Each row is (date, port, species, grade, low, high, avg).
    Best = highest avg across ports/grades for a species on a given date.
    """
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for date, _port, species, _grade, _low, _high, avg in rows:
        if avg is None:
            continue
        canonical = normalise_species(species)
        if canonical is None:
            continue
        if date not in out[canonical] or avg > out[canonical][date]:
            out[canonical][date] = avg
    return dict(out)


def _best_price_per_species_per_port(
    rows: list[tuple],
) -> dict[str, dict[str, list[float]]]:
    """Build {species: {port: [avg_values]}} across all rows."""
    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for _date, port, species, _grade, _low, _high, avg in rows:
        if avg is None:
            continue
        canonical = normalise_species(species)
        if canonical is None:
            continue
        out[canonical][port].append(avg)
    return dict(out)


def _port_daily_species_count(
    rows: list[tuple],
) -> dict[str, dict[str, int]]:
    """Build {port: {date: species_count}}."""
    seen: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for date, port, species, *_ in rows:
        canonical = normalise_species(species)
        if canonical is not None:
            seen[port][date].add(canonical)
    return {
        port: {date: len(spp) for date, spp in dates.items()}
        for port, dates in seen.items()
    }


def sparkline_svg(values: list[float | None], width: int = 60, height: int = 20) -> str:
    """Generate a tiny inline SVG polyline from a list of values."""
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return ""
    mn, mx = min(nums), max(nums)
    rng = mx - mn if mx != mn else 1.0
    points = []
    step = width / max(len(values) - 1, 1)
    for i, v in enumerate(values):
        if v is None:
            continue
        x = round(i * step, 1)
        y = round(height - ((v - mn) / rng) * (height - 2) - 1, 1)
        points.append(f"{x},{y}")
    if not points:
        return ""
    # Determine colour from trend
    colour = "#6db88a" if nums[-1] >= nums[0] else "#e07060"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle;">'
        f'<polyline points="{" ".join(points)}" fill="none" '
        f'stroke="{colour}" stroke-width="1.5" stroke-linecap="round"/>'
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Weekly review
# ---------------------------------------------------------------------------

def build_weekly_data(end_date: str | None = None) -> dict:
    """Assemble all data for the weekly review page.

    Parameters
    ----------
    end_date : str or None
        ISO date for the last day of the week. Defaults to the latest date
        with data. The week is the 5 most recent trading days up to and
        including *end_date*.
    """
    if end_date is None:
        end_date = get_latest_date()
    if not end_date:
        return {"error": "No data available"}

    # Determine the 7-calendar-day window ending on end_date
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=6)
    start_date = start_dt.strftime("%Y-%m-%d")

    # Also fetch the previous week for comparison
    prev_end_dt = start_dt - timedelta(days=1)
    prev_start_dt = prev_end_dt - timedelta(days=6)
    prev_start = prev_start_dt.strftime("%Y-%m-%d")
    prev_end = prev_end_dt.strftime("%Y-%m-%d")

    # Fetch data
    rows = get_prices_for_date_range(start_date, end_date)
    prev_rows = get_prices_for_date_range(prev_start, prev_end)
    trading_dates = get_trading_dates(start_date, end_date)

    if not rows:
        return {"error": "No data for this week"}

    # --- Summary strip ---
    all_species: set[str] = set()
    for _, _p, species, *_ in rows:
        canonical = normalise_species(species)
        if canonical is not None:
            all_species.add(canonical)

    avg_prices = []
    for _, _p, _s, _g, _l, _h, avg in rows:
        if avg is not None:
            avg_prices.append(avg)
    overall_avg = round(sum(avg_prices) / len(avg_prices), 2) if avg_prices else 0

    prev_avg_prices = [avg for *_, avg in prev_rows if avg is not None]
    prev_overall_avg = (
        round(sum(prev_avg_prices) / len(prev_avg_prices), 2)
        if prev_avg_prices
        else None
    )
    wow_change = None
    if prev_overall_avg and prev_overall_avg > 0:
        wow_change = round((overall_avg - prev_overall_avg) / prev_overall_avg * 100, 1)

    summary = {
        "trading_days": len(trading_dates),
        "species_count": len(all_species),
        "avg_price": overall_avg,
        "total_records": len(rows),
        "wow_change": wow_change,
    }

    # --- Weekly movers ---
    this_week_best = _best_price_per_species_per_date(rows)

    movers = []
    for species, date_prices in this_week_best.items():
        # Get first and last price in the week
        sorted_dates = sorted(date_prices.keys())
        if len(sorted_dates) < 2:
            continue
        first_price = date_prices[sorted_dates[0]]
        last_price = date_prices[sorted_dates[-1]]
        if first_price == 0:
            continue
        pct = round((last_price - first_price) / first_price * 100, 1)
        if abs(pct) < 0.5:
            continue
        # Sparkline values for the week's trading dates
        spark_values = [date_prices.get(d) for d in trading_dates]
        movers.append({
            "species": species,
            "start_price": round(first_price, 2),
            "end_price": round(last_price, 2),
            "change_pct": pct,
            "direction": "up" if pct > 0 else "down",
            "arrow": "\u25B2" if pct > 0 else "\u25BC",
            "sparkline": sparkline_svg(spark_values),
        })

    movers.sort(key=lambda m: abs(m["change_pct"]), reverse=True)
    risers = [m for m in movers if m["direction"] == "up"][:5]
    fallers = [m for m in movers if m["direction"] == "down"][:5]

    # --- Benchmark chart data ---
    species_port_prices = _best_price_per_species_per_port(rows)
    prev_species_port_prices = _best_price_per_species_per_port(prev_rows)

    benchmark_data = []
    for sp in BENCHMARK_SPECIES:
        port_prices = species_port_prices.get(sp, {})
        if not port_prices:
            continue
        # Best-per-port average: take max per port, then average across ports
        port_bests = [max(vals) for vals in port_prices.values() if vals]
        this_avg = round(sum(port_bests) / len(port_bests), 2) if port_bests else 0

        prev_port_prices = prev_species_port_prices.get(sp, {})
        prev_bests = [max(vals) for vals in prev_port_prices.values() if vals]
        prev_avg = round(sum(prev_bests) / len(prev_bests), 2) if prev_bests else None

        benchmark_data.append({
            "species": sp,
            "this_week": this_avg,
            "last_week": prev_avg,
        })

    # --- Port activity heatmap ---
    port_daily = _port_daily_species_count(rows)
    ports_list = sorted(port_daily.keys())

    heatmap = []
    for port in ports_list:
        days_data = []
        for d in trading_dates:
            count = port_daily.get(port, {}).get(d, 0)
            days_data.append({"date": d, "count": count})
        code = PORT_CODES.get(port, port[:3].upper())
        heatmap.append({"port": port, "code": code, "days": days_data})

    # --- Best value by port ---
    # Average price per port across shared species
    port_avg: dict[str, list[float]] = defaultdict(list)
    for sp, port_prices in species_port_prices.items():
        for port, vals in port_prices.items():
            port_avg[port].extend(vals)

    market_overall = overall_avg
    value_ranking = []
    for port in sorted(port_avg.keys()):
        vals = port_avg[port]
        avg = round(sum(vals) / len(vals), 2)
        vs_market = round((avg - market_overall) / market_overall * 100, 1) if market_overall else 0
        code = PORT_CODES.get(port, port[:3].upper())
        value_ranking.append({
            "port": port,
            "code": code,
            "avg_price": avg,
            "vs_market": vs_market,
            "record_count": len(vals),
        })
    value_ranking.sort(key=lambda p: p["avg_price"])

    # --- Cross-port spreads ---
    spreads = []
    for sp, port_prices in species_port_prices.items():
        if len(port_prices) < 2:
            continue
        port_avgs = {}
        for port, vals in port_prices.items():
            port_avgs[port] = round(sum(vals) / len(vals), 2)
        sorted_ports = sorted(port_avgs.items(), key=lambda x: x[1])
        low_port, low_price = sorted_ports[0]
        high_port, high_price = sorted_ports[-1]
        if low_price == 0:
            continue
        spread_pct = round((high_price - low_price) / low_price * 100, 1)
        spreads.append({
            "species": sp,
            "high_port": high_port,
            "high_code": PORT_CODES.get(high_port, high_port[:3].upper()),
            "high_price": high_price,
            "low_port": low_port,
            "low_code": PORT_CODES.get(low_port, low_port[:3].upper()),
            "low_price": low_price,
            "spread_pct": spread_pct,
        })
    spreads.sort(key=lambda s: s["spread_pct"], reverse=True)

    return {
        "period_label": f"Week ending {end_date}",
        "start_date": start_date,
        "end_date": end_date,
        "trading_dates": trading_dates,
        "summary": summary,
        "risers": risers,
        "fallers": fallers,
        "benchmark_data": benchmark_data,
        "heatmap": heatmap,
        "value_ranking": value_ranking,
        "spreads": spreads[:5],
    }


# ---------------------------------------------------------------------------
# Monthly review
# ---------------------------------------------------------------------------

def build_monthly_data(year_month: str | None = None) -> dict:
    """Assemble all data for the monthly review page.

    Parameters
    ----------
    year_month : str or None
        Format ``YYYY-MM``. Defaults to the month of the latest data.
    """
    latest = get_latest_date()
    if not latest:
        return {"error": "No data available"}

    if year_month is None:
        year_month = latest[:7]  # "2026-03"

    # Date range for the month
    year, month = int(year_month[:4]), int(year_month[5:7])
    start_date = f"{year_month}-01"
    # Last day of month
    if month == 12:
        next_month_dt = datetime(year + 1, 1, 1)
    else:
        next_month_dt = datetime(year, month + 1, 1)
    end_date = (next_month_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    # Previous month for comparison
    prev_month_dt = datetime(year, month, 1) - timedelta(days=1)
    prev_start = prev_month_dt.replace(day=1).strftime("%Y-%m-%d")
    prev_end = prev_month_dt.strftime("%Y-%m-%d")

    # Fetch data
    rows = get_prices_for_date_range(start_date, end_date)
    prev_rows = get_prices_for_date_range(prev_start, prev_end)
    trading_dates = get_trading_dates(start_date, end_date)

    if not rows:
        return {"error": "No data for this month"}

    # --- Summary ---
    all_species: set[str] = set()
    all_ports: set[str] = set()
    for _, port, species, *_ in rows:
        canonical = normalise_species(species)
        if canonical is not None:
            all_species.add(canonical)
        all_ports.add(port)

    summary = {
        "trading_days": len(trading_dates),
        "ports_active": len(all_ports),
        "total_records": len(rows),
        "species_count": len(all_species),
    }

    # --- Trend charts for benchmark species ---
    # {species: {port: {date: best_avg}}}
    trend_data: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for date, port, species, _grade, _low, _high, avg in rows:
        if avg is None:
            continue
        canonical = normalise_species(species)
        if canonical not in BENCHMARK_SPECIES:
            continue
        existing = trend_data[canonical][port].get(date)
        if existing is None or avg > existing:
            trend_data[canonical][port][date] = avg

    chart_colors = [
        "#1a3a4a", "#c8401a", "#6db88a", "#e07060", "#7a7060",
        "#4a8a6a", "#c07830", "#3a6a8a",
    ]

    trend_charts = []
    for sp in BENCHMARK_SPECIES:
        if sp not in trend_data:
            continue
        datasets = []
        for i, (port, date_prices) in enumerate(sorted(trend_data[sp].items())):
            code = PORT_CODES.get(port, port[:3].upper())
            data = [date_prices.get(d) for d in trading_dates]
            datasets.append({
                "label": code,
                "data": data,
                "borderColor": chart_colors[i % len(chart_colors)],
            })
        trend_charts.append({
            "species": sp,
            "labels": trading_dates,
            "datasets": datasets,
        })

    # --- Volatility ranking ---
    species_daily = _best_price_per_species_per_date(rows)
    volatility = []
    for species, date_prices in species_daily.items():
        vals = list(date_prices.values())
        if len(vals) < 3:
            continue
        avg = sum(vals) / len(vals)
        std = math.sqrt(sum((v - avg) ** 2 for v in vals) / len(vals))
        sorted_dates = sorted(date_prices.keys())
        first_val = date_prices[sorted_dates[0]]
        last_val = date_prices[sorted_dates[-1]]
        trend_pct = round((last_val - first_val) / first_val * 100, 1) if first_val else 0
        volatility.append({
            "species": species,
            "avg": round(avg, 2),
            "high": round(max(vals), 2),
            "low": round(min(vals), 2),
            "std_dev": round(std, 2),
            "trend_pct": trend_pct,
            "trend_dir": "up" if trend_pct > 0 else ("down" if trend_pct < 0 else "flat"),
        })
    volatility.sort(key=lambda v: v["std_dev"], reverse=True)

    # --- Port reliability ---
    port_daily = _port_daily_species_count(rows)
    possible_days = len(trading_dates) or 1
    reliability = []
    for port in sorted(port_daily.keys()):
        days_data = port_daily[port]
        days_reporting = len(days_data)
        species_counts = list(days_data.values())
        avg_species = round(sum(species_counts) / len(species_counts), 1) if species_counts else 0
        completeness = round(days_reporting / possible_days * 100)
        code = PORT_CODES.get(port, port[:3].upper())
        reliability.append({
            "port": port,
            "code": code,
            "days_reporting": days_reporting,
            "possible_days": possible_days,
            "avg_species": avg_species,
            "completeness": completeness,
        })
    reliability.sort(key=lambda r: r["completeness"], reverse=True)

    # --- Species availability matrix ---
    # {species: {port: days_count}}
    availability: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    seen_per_day: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for date, port, species, *_ in rows:
        canonical = normalise_species(species)
        if canonical is not None:
            seen_per_day[canonical][port].add(date)
    for species, port_dates in seen_per_day.items():
        for port, dates in port_dates.items():
            availability[species][port] = len(dates)

    avail_ports = sorted(all_ports)
    avail_species = sorted(availability.keys())
    availability_matrix = {
        "ports": avail_ports,
        "port_codes": [PORT_CODES.get(p, p[:3].upper()) for p in avail_ports],
        "species": [],
    }
    for sp in avail_species:
        row = {
            "name": sp,
            "counts": [availability[sp].get(p, 0) for p in avail_ports],
        }
        availability_matrix["species"].append(row)

    # --- Month-over-month comparison ---
    prev_daily = _best_price_per_species_per_date(prev_rows)
    mom_comparison = []
    for sp in BENCHMARK_SPECIES:
        this_vals = list(species_daily.get(sp, {}).values())
        prev_vals = list(prev_daily.get(sp, {}).values())
        if not this_vals:
            continue
        this_avg = round(sum(this_vals) / len(this_vals), 2)
        prev_avg = round(sum(prev_vals) / len(prev_vals), 2) if prev_vals else None
        change_pct = None
        if prev_avg and prev_avg > 0:
            change_pct = round((this_avg - prev_avg) / prev_avg * 100, 1)
        mom_comparison.append({
            "species": sp,
            "this_month": this_avg,
            "last_month": prev_avg,
            "change_pct": change_pct,
            "direction": "up" if (change_pct and change_pct > 0) else ("down" if (change_pct and change_pct < 0) else "flat"),
        })

    # Month label
    month_label = datetime(year, month, 1).strftime("%B %Y")

    return {
        "period_label": month_label,
        "year_month": year_month,
        "start_date": start_date,
        "end_date": end_date,
        "trading_dates": trading_dates,
        "summary": summary,
        "trend_charts": trend_charts,
        "volatility": volatility,
        "reliability": reliability,
        "availability_matrix": availability_matrix,
        "mom_comparison": mom_comparison,
    }
