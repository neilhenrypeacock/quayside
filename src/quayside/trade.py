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
    get_all_time_market_stats,
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


# ── Highlights ────────────────────────────────────────────────────────────────

def _highlights_today(matrix: list[dict], port_code_map: dict) -> list[dict]:
    """Plain-English insights for today vs yesterday."""
    out = []

    # Biggest daily mover up
    risers = sorted(
        [r for r in matrix if r["vs_yesterday_pct"] is not None and r["vs_yesterday_pct"] > 0],
        key=lambda r: r["vs_yesterday_pct"], reverse=True,
    )
    if risers:
        r = risers[0]
        port_note = ""
        if r["best_buy_port"]:
            port_note = f" — cheapest at {port_code_map.get(r['best_buy_port'], r['best_buy_port'][:3])} £{r['best_buy_price']:.2f}/kg"
        out.append({
            "type": "up",
            "species": r["species"],
            "text": f"<em>{r['species']}</em> up +{r['vs_yesterday_pct']:.1f}% vs yesterday{port_note}",
        })

    # Biggest daily mover down
    fallers = sorted(
        [r for r in matrix if r["vs_yesterday_pct"] is not None and r["vs_yesterday_pct"] < 0],
        key=lambda r: r["vs_yesterday_pct"],
    )
    if fallers:
        f = fallers[0]
        out.append({
            "type": "down",
            "species": f["species"],
            "text": f"<em>{f['species']}</em> fell {f['vs_yesterday_pct']:.1f}% vs yesterday market-wide",
        })

    # Widest spread → arbitrage
    spreads = sorted(
        [r for r in matrix if r["spread_pct"] is not None and r["spread_pct"] > 0],
        key=lambda r: r["spread_pct"], reverse=True,
    )
    if spreads:
        s = spreads[0]
        low_code = port_code_map.get(s["best_buy_port"], s["best_buy_port"][:3])
        high_port = max(s["ports"], key=s["ports"].get)
        high_code = port_code_map.get(high_port, high_port[:3])
        out.append({
            "type": "opportunity",
            "species": s["species"],
            "text": (
                f"<em>{s['species']}</em> cross-port spread: {s['spread_pct']:.0f}% — "
                f"buy at {low_code} £{s['best_buy_price']:.2f}/kg vs {high_code} £{s['ports'][high_port]:.2f}/kg"
            ),
        })

    # Best value vs 30d avg (most below)
    value_buys = sorted(
        [r for r in matrix if r["vs_30d_pct"] is not None and r["vs_30d_pct"] < -5],
        key=lambda r: r["vs_30d_pct"],
    )
    if value_buys:
        v = value_buys[0]
        out.append({
            "type": "value",
            "species": v["species"],
            "text": (
                f"<em>{v['species']}</em> is {abs(v['vs_30d_pct']):.1f}% below its 30-day average "
                f"— potential buy opportunity at £{v['market_avg']:.2f}/kg"
            ),
        })

    # Most above 30d avg (expensive)
    expensive = sorted(
        [r for r in matrix if r["vs_30d_pct"] is not None and r["vs_30d_pct"] > 10],
        key=lambda r: r["vs_30d_pct"], reverse=True,
    )
    if expensive:
        e = expensive[0]
        out.append({
            "type": "context",
            "species": e["species"],
            "text": (
                f"<em>{e['species']}</em> running {e['vs_30d_pct']:.1f}% above its 30-day average "
                f"at £{e['market_avg']:.2f}/kg"
            ),
        })

    return out[:5]


def _highlights_week(
    matrix: list[dict],
    species_7d: dict[str, list[float | None]],
    port_code_map: dict,
) -> list[dict]:
    """Plain-English insights for 7-day trends."""
    out = []

    # Build week-over-week deltas from 7d series
    week_movers = []
    for sp, series in species_7d.items():
        nums = [(i, v) for i, v in enumerate(series) if v is not None]
        if len(nums) < 3:
            continue
        first_val = nums[0][1]
        last_val = nums[-1][1]
        if first_val <= 0:
            continue
        pct = round((last_val - first_val) / first_val * 100, 1)
        week_movers.append({"species": sp, "pct": pct, "current": last_val})

    week_movers.sort(key=lambda m: m["pct"], reverse=True)
    risers = [m for m in week_movers if m["pct"] > 0]
    fallers = [m for m in week_movers if m["pct"] < 0]

    if risers:
        r = risers[0]
        out.append({
            "type": "up",
            "species": r["species"],
            "text": f"<em>{r['species']}</em> has risen +{r['pct']:.1f}% over the past 7 days — now £{r['current']:.2f}/kg",
        })
    if len(risers) > 1:
        r2 = risers[1]
        out.append({
            "type": "up",
            "species": r2["species"],
            "text": f"<em>{r2['species']}</em> also gaining this week: +{r2['pct']:.1f}% at £{r2['current']:.2f}/kg",
        })

    if fallers:
        f = fallers[-1]
        out.append({
            "type": "down",
            "species": f["species"],
            "text": f"<em>{f['species']}</em> dropped {f['pct']:.1f}% this week — now £{f['current']:.2f}/kg",
        })

    # Best buy this week (current best_buy_port)
    port_scores: dict[str, int] = defaultdict(int)
    for row in matrix:
        if row.get("best_buy_port"):
            port_scores[row["best_buy_port"]] += 1
    if port_scores:
        top_port = max(port_scores, key=port_scores.get)
        count = port_scores[top_port]
        code = port_code_map.get(top_port, top_port[:3])
        out.append({
            "type": "value",
            "species": None,
            "text": f"{top_port} ({code}) offering best prices on {count} species today",
        })

    return out[:5]


def _highlights_month(matrix: list[dict], port_code_map: dict) -> list[dict]:
    """Plain-English insights based on 30-day averages."""
    out = []

    # Species most below 30d avg
    below = sorted(
        [r for r in matrix if r["vs_30d_pct"] is not None and r["vs_30d_pct"] < 0],
        key=lambda r: r["vs_30d_pct"],
    )
    for r in below[:2]:
        out.append({
            "type": "value",
            "species": r["species"],
            "text": (
                f"<em>{r['species']}</em> is {abs(r['vs_30d_pct']):.1f}% below its monthly average — "
                f"30d avg £{r['thirty_day_avg']:.2f}, today £{r['market_avg']:.2f}/kg"
            ),
        })

    # Species most above 30d avg
    above = sorted(
        [r for r in matrix if r["vs_30d_pct"] is not None and r["vs_30d_pct"] > 0],
        key=lambda r: r["vs_30d_pct"], reverse=True,
    )
    for r in above[:2]:
        out.append({
            "type": "context",
            "species": r["species"],
            "text": (
                f"<em>{r['species']}</em> up {r['vs_30d_pct']:.1f}% on its monthly average — "
                f"30d avg £{r['thirty_day_avg']:.2f}, today £{r['market_avg']:.2f}/kg"
            ),
        })

    # Widest sustained spread this month
    spreads = sorted(
        [r for r in matrix if r["spread_pct"] is not None],
        key=lambda r: r["spread_pct"], reverse=True,
    )
    if spreads:
        s = spreads[0]
        out.append({
            "type": "opportunity",
            "species": s["species"],
            "text": (
                f"<em>{s['species']}</em> consistently showing the widest cross-port spread "
                f"— {s['spread_pct']:.0f}% gap between ports today"
            ),
        })

    return out[:5]


def _highlights_ytd(date: str, matrix: list[dict], port_code_map: dict) -> list[dict]:
    """Plain-English insights vs start-of-year prices."""
    out = []
    dt = datetime.strptime(date, "%Y-%m-%d")
    year_start = f"{dt.year}-01-01"
    year_end = f"{dt.year}-01-31"

    # Fetch Jan data for YTD baseline
    jan_rows = get_prices_for_date_range(year_start, year_end)
    jan_by_species: dict[str, list[float]] = defaultdict(list)
    for _d, _port, raw_sp, _grade, _low, _high, avg in jan_rows:
        if avg is not None:
            jan_by_species[normalise_species(raw_sp)].append(avg)

    jan_avgs = {sp: sum(v) / len(v) for sp, v in jan_by_species.items() if v}

    ytd_movers = []
    for row in matrix:
        sp = row["species"]
        if sp not in jan_avgs or jan_avgs[sp] <= 0:
            continue
        pct = round((row["market_avg"] - jan_avgs[sp]) / jan_avgs[sp] * 100, 1)
        ytd_movers.append({"species": sp, "pct": pct, "current": row["market_avg"], "jan_avg": jan_avgs[sp]})

    ytd_movers.sort(key=lambda m: m["pct"], reverse=True)

    for m in ytd_movers[:2]:
        direction = "up" if m["pct"] > 0 else "down"
        sign = "+" if m["pct"] > 0 else ""
        out.append({
            "type": direction,
            "species": m["species"],
            "text": (
                f"<em>{m['species']}</em> {sign}{m['pct']:.1f}% YTD — "
                f"Jan avg £{m['jan_avg']:.2f}, now £{m['current']:.2f}/kg"
            ),
        })

    if len(ytd_movers) > 2:
        for m in ytd_movers[-2:]:
            direction = "up" if m["pct"] > 0 else "down"
            sign = "+" if m["pct"] > 0 else ""
            out.append({
                "type": direction,
                "species": m["species"],
                "text": (
                    f"<em>{m['species']}</em> {sign}{m['pct']:.1f}% YTD — "
                    f"Jan avg £{m['jan_avg']:.2f}, now £{m['current']:.2f}/kg"
                ),
            })

    if not ytd_movers:
        out.append({
            "type": "context",
            "species": None,
            "text": f"YTD data comparison unavailable — no January {dt.year} prices in database",
        })

    return out[:5]


def build_highlights(
    date: str,
    matrix: list[dict],
    port_code_map: dict,
    species_7d: dict[str, list[float | None]],
) -> dict[str, list[dict]]:
    """Build plain-English insight bullets for all 4 timeframes."""
    return {
        "today": _highlights_today(matrix, port_code_map),
        "week": _highlights_week(matrix, species_7d, port_code_map),
        "month": _highlights_month(matrix, port_code_map),
        "ytd": _highlights_ytd(date, matrix, port_code_map),
    }


# ── Compare view ──────────────────────────────────────────────────────────────

def build_compare_data(date_a: str, date_b: str) -> dict:
    """Build comparison matrix between two dates for the Compare view."""
    port_code_map = _port_codes()

    rows_a = get_all_prices_for_date(date_a, exclude_demo=True)
    rows_b = get_all_prices_for_date(date_b, exclude_demo=True)

    matrix_a = _best_price_per_port(rows_a)
    matrix_b = _best_price_per_port(rows_b)

    # Union of all species in either date
    all_species = sorted(set(matrix_a.keys()) | set(matrix_b.keys()))
    # Union of all ports
    all_ports_set: set[str] = set()
    for d in (matrix_a, matrix_b):
        for pp in d.values():
            all_ports_set.update(pp.keys())
    all_ports = sorted(all_ports_set)

    rows = []
    for species in all_species:
        if is_noisy_species(species):
            continue
        ports_a = matrix_a.get(species, {})
        ports_b = matrix_b.get(species, {})

        prices_a = list(ports_a.values())
        prices_b = list(ports_b.values())
        mkt_a = round(sum(prices_a) / len(prices_a), 2) if prices_a else None
        mkt_b = round(sum(prices_b) / len(prices_b), 2) if prices_b else None

        delta_pct = None
        if mkt_a and mkt_b and mkt_b > 0:
            delta_pct = round((mkt_a - mkt_b) / mkt_b * 100, 1)

        rows.append({
            "species": species,
            "category": get_species_category(species),
            "ports_a": ports_a,
            "ports_b": ports_b,
            "mkt_a": mkt_a,
            "mkt_b": mkt_b,
            "delta_pct": delta_pct,
        })

    return {
        "date_a": date_a,
        "date_b": date_b,
        "all_ports": all_ports,
        "port_codes": port_code_map,
        "rows": rows,
    }


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

    # 7-day rolling window for vs_7d metrics (calendar days)
    start_7d_raw = (dt - timedelta(days=7)).strftime("%Y-%m-%d")

    port_code_map = _port_codes()
    active_ports = get_all_ports(status="active")
    active_port_names = [p["name"] for p in active_ports]

    # 7-day per-species rolling averages (canonical names, from rows_90d)
    _seven_accum: dict[str, list[float]] = defaultdict(list)
    for _d, _port, raw_sp, _grade, _low, _high, _avg in rows_90d:
        if _avg is not None and _d >= start_7d_raw and _d < date:
            _seven_accum[normalise_species(raw_sp)].append(_avg)
    seven_day_avgs: dict[str, float] = {
        sp: round(sum(vals) / len(vals), 2) for sp, vals in _seven_accum.items()
    }

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

        seven_avg = seven_day_avgs.get(species)
        vs_7d_pct: float | None = None
        vs_7d_direction = "flat"
        if seven_avg and seven_avg > 0:
            vs_7d_pct = round((market_avg - seven_avg) / seven_avg * 100, 1)
            vs_7d_direction = "up" if vs_7d_pct > 0 else ("down" if vs_7d_pct < 0 else "flat")

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
            "seven_day_avg": seven_avg,
            "vs_7d_pct": vs_7d_pct,
            "vs_7d_direction": vs_7d_direction,
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

    # Market vs 30-day average (aggregate across all species)
    today_prices_all = [r["market_avg"] for r in matrix]
    thirty_day_prices_all = [r["thirty_day_avg"] for r in matrix if r["thirty_day_avg"] is not None]
    today_grand_avg = round(sum(today_prices_all) / len(today_prices_all), 2) if today_prices_all else None
    thirty_day_grand_avg = round(sum(thirty_day_prices_all) / len(thirty_day_prices_all), 2) if thirty_day_prices_all else None
    vs_30d_market_pct: float | None = None
    vs_30d_market_label = "flat"
    if today_grand_avg and thirty_day_grand_avg and thirty_day_grand_avg > 0:
        vs_30d_market_pct = round((today_grand_avg - thirty_day_grand_avg) / thirty_day_grand_avg * 100, 1)
        vs_30d_market_label = "up" if vs_30d_market_pct > 0 else ("down" if vs_30d_market_pct < 0 else "flat")

    # Market vs 7-day average
    seven_day_market_prices: list[float] = []
    for d, _port, _raw_sp, _grade, _low, _high, avg in rows_90d:
        if avg is not None and d >= start_7d_raw and d < date:
            seven_day_market_prices.append(avg)
    seven_day_grand_avg = round(sum(seven_day_market_prices) / len(seven_day_market_prices), 2) if seven_day_market_prices else None
    vs_7d_market_pct: float | None = None
    vs_7d_market_label = "flat"
    if today_grand_avg and seven_day_grand_avg and seven_day_grand_avg > 0:
        vs_7d_market_pct = round((today_grand_avg - seven_day_grand_avg) / seven_day_grand_avg * 100, 1)
        vs_7d_market_label = "up" if vs_7d_market_pct > 0 else ("down" if vs_7d_market_pct < 0 else "flat")

    # Market vs all-time average (since data collection began)
    data_start_date, all_time_grand_avg = get_all_time_market_stats()
    vs_alltime_market_pct: float | None = None
    vs_alltime_market_label = "flat"
    if today_grand_avg and all_time_grand_avg and all_time_grand_avg > 0:
        vs_alltime_market_pct = round((today_grand_avg - all_time_grand_avg) / all_time_grand_avg * 100, 1)
        vs_alltime_market_label = "up" if vs_alltime_market_pct > 0 else ("down" if vs_alltime_market_pct < 0 else "flat")
    data_start_display = datetime.strptime(data_start_date, "%Y-%m-%d").strftime("%b %Y") if data_start_date else "—"

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

    pulse = {
        "ports_reporting": ports_reporting,
        "ports_total": ports_total,
        "species_tracked": species_tracked,
        "market_direction_pct": market_direction_pct,
        "market_direction_label": market_direction_label,
        "market_direction_arrow": market_direction_arrow,
        "vs_30d_market_pct": vs_30d_market_pct,
        "vs_30d_market_label": vs_30d_market_label,
        "vs_7d_market_pct": vs_7d_market_pct,
        "vs_7d_market_label": vs_7d_market_label,
        "vs_alltime_market_pct": vs_alltime_market_pct,
        "vs_alltime_market_label": vs_alltime_market_label,
        "data_start_date": data_start_display,
        "best_value_port": best_value_port,
        "best_value_port_avg": best_value_port_avg,
    }

    # ── Per-category pulse stats (for JS filter updates) ──────────────────────
    category_pulse: dict[str, dict] = {}
    for cat in ["all", "demersal", "flatfish", "shellfish", "pelagic", "other"]:
        filtered = [r for r in matrix if cat == "all" or r["category"] == cat]
        yest_vals = [r["vs_yesterday_pct"] for r in filtered if r["vs_yesterday_pct"] is not None]
        sevend_vals = [r["vs_7d_pct"] for r in filtered if r["vs_7d_pct"] is not None]
        thirtyd_vals = [r["vs_30d_pct"] for r in filtered if r["vs_30d_pct"] is not None]
        today_avgs = [r["market_avg"] for r in filtered]
        today_cat_avg = sum(today_avgs) / len(today_avgs) if today_avgs else None
        vs_alltime_cat = round((today_cat_avg - all_time_grand_avg) / all_time_grand_avg * 100, 1) if (today_cat_avg and all_time_grand_avg and all_time_grand_avg > 0) else None
        category_pulse[cat] = {
            "vs_yest": round(sum(yest_vals) / len(yest_vals), 1) if yest_vals else None,
            "vs_7d": round(sum(sevend_vals) / len(sevend_vals), 1) if sevend_vals else None,
            "vs_30d": round(sum(thirtyd_vals) / len(thirtyd_vals), 1) if thirtyd_vals else None,
            "vs_alltime": vs_alltime_cat,
        }
    for row in matrix:
        vs_alltime_sp = round((row["market_avg"] - all_time_grand_avg) / all_time_grand_avg * 100, 1) if (all_time_grand_avg and all_time_grand_avg > 0) else None
        category_pulse[f"species:{row['species']}"] = {
            "vs_yest": row["vs_yesterday_pct"],
            "vs_7d": row["vs_7d_pct"],
            "vs_30d": row["vs_30d_pct"],
            "vs_alltime": vs_alltime_sp,
        }

    # ── Port status strip ─────────────────────────────────────────────────────
    port_species_count: dict[str, int] = defaultdict(int)
    for row in matrix:
        for port in row["ports"]:
            port_species_count[port] += 1

    # Include all active ports, even those not reporting today (exclude demo)
    demo_names = {p["name"] for p in active_ports if p.get("data_method") == "demo"}
    status_ports = sorted((set(active_port_names) | ports_today) - demo_names)
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

    # ── Highlights ────────────────────────────────────────────────────────────
    highlights = build_highlights(date, matrix, port_code_map, species_7d)

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
        "category_pulse": category_pulse,
        "port_status": port_status,
        "matrix": matrix,
        "arbitrage": arbitrage,
        "momentum": {"risers": risers, "fallers": fallers},
        "chart_data": chart_data,
        "ninety_days_ago": ninety_days_ago,
        "highlights": highlights,
        "generated_at": datetime.now().strftime("%H:%M"),
    }
