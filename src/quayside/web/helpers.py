"""Shared helper functions for port dashboard data building."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from quayside.db import (
    get_all_prices_for_date,
    get_connection,
    get_market_averages_for_date,
    get_market_averages_for_range,
    get_port_prices_history,
    get_previous_date,
    get_prices_for_date_range,
    get_trading_dates_recent,
)
from quayside.models import PriceRecord
from quayside.species import get_species_category, normalise_species


def pct_in_range(value: float, min_val: float, max_val: float) -> int:
    """Calculate where a value sits in a range as a percentage (0-100)."""
    if max_val == min_val:
        return 50
    return max(0, min(100, round(((value - min_val) / (max_val - min_val)) * 100)))


def build_today_data(
    port_prices: list[tuple],
    market: dict,
    last_week_prices: dict,
) -> list[dict]:
    """Build normalised price rows with market position and vs-last-week delta.

    Shared by the port dashboard route and the prices_partial HTMX route.
    """
    today_data = []
    for row in port_prices:
        _, _, species, grade, low, high, avg, weight_kg, boxes = row
        canonical = normalise_species(species)
        if canonical is None:
            continue  # skip noisy/unrecognised species
        market_info = market.get(canonical, {})

        position = None
        if avg and market_info.get("port_count", 0) >= 2:
            market_avg = market_info["avg"]
            market_min = market_info["min"]
            market_max = market_info["max"]
            is_best = avg >= market_max
            is_below = avg < market_avg * 0.95
            vs_pct = round(((avg - market_avg) / market_avg) * 100, 1)
            position = {
                "market_avg": round(market_avg, 2),
                "market_min": round(market_min, 2),
                "market_max": round(market_max, 2),
                "port_count": market_info["port_count"],
                "is_best": is_best,
                "is_below": is_below,
                "vs_pct": vs_pct,
                "pct_of_range": pct_in_range(avg, market_min, market_max),
            }

        lw = last_week_prices.get((species, grade))
        vs_last_week = None
        if lw and lw["price_avg"] and avg:
            vs_last_week = round(((avg - lw["price_avg"]) / lw["price_avg"]) * 100, 1)

        today_data.append({
            "species": canonical,
            "raw_species": species,
            "grade": grade,
            "price_low": low,
            "price_high": high,
            "price_avg": avg,
            "weight_kg": weight_kg,
            "boxes": boxes,
            "position": position,
            "vs_last_week": vs_last_week,
            "category": get_species_category(canonical),
        })
    return today_data


def build_trend_data(
    history: list[tuple],
    market_avgs: dict[str, dict[str, float]] | None = None,
) -> dict:
    """Build trend data for chart.js from price history rows.

    market_avgs: optional {date: {raw_species: market_avg}} from
    get_market_averages_for_range — used to overlay the real UK market average.
    """
    species_dates: dict[str, dict[str, float]] = defaultdict(dict)

    for date, species, _grade, _low, _high, avg in history:
        canonical = normalise_species(species)
        if canonical is None:
            continue
        if avg and (date not in species_dates[canonical] or avg > species_dates[canonical][date]):
            species_dates[canonical][date] = avg

    # Get top 5 species by frequency
    species_freq = sorted(species_dates.keys(), key=lambda s: len(species_dates[s]), reverse=True)
    top_species = species_freq[:5]

    # Build chart data
    all_dates = sorted({d for sp in top_species for d in species_dates[sp]})

    # Pre-build normalised market avg lookup: {canonical_species: {date: avg}}
    market_by_canonical: dict[str, dict[str, float]] = defaultdict(dict)
    if market_avgs:
        for m_date, species_map in market_avgs.items():
            for raw_sp, avg in species_map.items():
                canon = normalise_species(raw_sp)
                if canon is not None:
                    market_by_canonical[canon][m_date] = avg

    datasets = []
    for sp in top_species:
        ds: dict = {
            "label": sp,
            "data": [species_dates[sp].get(d) for d in all_dates],
        }
        if market_avgs:
            ds["market_avg"] = [market_by_canonical[sp].get(d) for d in all_dates]
        datasets.append(ds)

    return {"labels": all_dates, "datasets": datasets}


def build_best_performers(
    port_name: str, date: str, days: int = 30,
) -> dict:
    """Build strongest species and best days data for a port."""
    end_date = date
    start_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")

    # Get this port's history
    port_history = get_port_prices_history(port_name, days=days)
    # Get market averages for the same range
    market_range = get_market_averages_for_range(start_date, end_date)

    # Group port prices by (date, species) -> best avg
    port_by_date_species: dict[str, dict[str, float]] = defaultdict(dict)
    for hist_date, species, _grade, _low, _high, avg in port_history:
        if avg:
            canonical = normalise_species(species)
            if canonical is None:
                continue
            if canonical not in port_by_date_species[hist_date] or avg > port_by_date_species[hist_date][canonical]:
                port_by_date_species[hist_date][canonical] = avg

    # --- Strongest species: % above market average over period ---
    species_vs_market: dict[str, list[float]] = defaultdict(list)
    species_above_count: dict[str, int] = defaultdict(int)
    species_total_days: dict[str, int] = defaultdict(int)
    species_avg_price: dict[str, list[float]] = defaultdict(list)

    for hist_date, species_prices in port_by_date_species.items():
        market_day = market_range.get(hist_date, {})
        for species, price in species_prices.items():
            raw_market = market_day.get(species)
            if raw_market and raw_market > 0:
                vs_pct = ((price - raw_market) / raw_market) * 100
                species_vs_market[species].append(vs_pct)
                species_total_days[species] += 1
                if vs_pct > 0:
                    species_above_count[species] += 1
            species_avg_price[species].append(price)

    strongest = []
    for species, vs_list in species_vs_market.items():
        avg_vs = sum(vs_list) / len(vs_list)
        avg_price = sum(species_avg_price[species]) / len(species_avg_price[species])
        total_days = species_total_days[species]
        above_days = species_above_count[species]
        strongest.append({
            "species": species,
            "avg_price": round(avg_price, 2),
            "vs_market_pct": round(avg_vs, 1),
            "above_days": above_days,
            "total_days": total_days,
        })
    strongest.sort(key=lambda x: x["vs_market_pct"], reverse=True)

    # --- Month summary: holistic top-line view ---
    trading_dates = sorted(port_by_date_species.keys())
    total_sessions = len(trading_dates)

    # Per-day stats: avg price and species count
    day_stats = []
    all_month_prices = []
    for d in trading_dates:
        prices = list(port_by_date_species[d].values())
        day_avg = sum(prices) / len(prices) if prices else 0
        day_stats.append({
            "date": d,
            "avg_price": round(day_avg, 2),
            "species_count": len(prices),
        })
        all_month_prices.extend(prices)

    month_avg = round(
        sum(all_month_prices) / len(all_month_prices), 2,
    ) if all_month_prices else 0

    # First half vs second half trend
    month_trend_pct = None
    if len(day_stats) >= 4:
        mid = len(day_stats) // 2
        first_half = [p for ds in day_stats[:mid] for p in port_by_date_species[ds["date"]].values()]
        second_half = [p for ds in day_stats[mid:] for p in port_by_date_species[ds["date"]].values()]
        if first_half and second_half:
            fh_avg = sum(first_half) / len(first_half)
            sh_avg = sum(second_half) / len(second_half)
            if fh_avg > 0:
                month_trend_pct = round(((sh_avg - fh_avg) / fh_avg) * 100, 1)

    # Busiest and quietest days
    busiest = max(day_stats, key=lambda x: x["species_count"]) if day_stats else None
    quietest = min(day_stats, key=lambda x: x["species_count"]) if day_stats else None

    # Highest and lowest avg price days
    best_price_day = max(day_stats, key=lambda x: x["avg_price"]) if day_stats else None
    worst_price_day = min(day_stats, key=lambda x: x["avg_price"]) if day_stats else None

    # Unique species this month
    all_month_species = set()
    for d_prices in port_by_date_species.values():
        all_month_species.update(d_prices.keys())

    month_summary = {
        "total_sessions": total_sessions,
        "month_avg": month_avg,
        "month_trend_pct": month_trend_pct,
        "total_species": len(all_month_species),
        "busiest_day": busiest,
        "quietest_day": quietest,
        "best_price_day": best_price_day,
        "worst_price_day": worst_price_day,
    }

    return {
        "strongest_species": strongest[:5],
        "month_summary": month_summary,
    }


def build_insights(
    port_name: str, date: str, today_data: list[dict],
    history: list[tuple],
) -> dict:
    """Generate rule-based insights split into port-specific and market-wide.

    Returns {"port": [...], "market": [...]}.
    """
    # Get market averages for today
    market = get_market_averages_for_date(date)

    # Each insight gets a priority (lower = more important) for ranking
    _ranked_port: list[tuple[int, dict]] = []
    _ranked_market: list[tuple[int, dict]] = []

    recent_dates = sorted({h[0] for h in history}, reverse=True)

    # === PORT INTELLIGENCE — historical performance patterns ===

    # --- Day-of-week pattern ---
    dow_prices: dict[int, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            try:
                dow = datetime.strptime(hist_date, "%Y-%m-%d").weekday()
                dow_prices[dow].append(avg)
            except ValueError:
                pass

    if dow_prices:
        dow_avgs = {
            dow: sum(prices) / len(prices)
            for dow, prices in dow_prices.items()
        }
        best_dow = max(dow_avgs, key=dow_avgs.get)
        best_dow_avg = dow_avgs[best_dow]
        other_avg = sum(
            v for k, v in dow_avgs.items() if k != best_dow
        ) / max(1, len(dow_avgs) - 1)
        if other_avg > 0 and ((best_dow_avg - other_avg) / other_avg) > 0.02:
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
            if best_dow < 5:
                pct_diff = round(((best_dow_avg - other_avg) / other_avg) * 100, 1)
                _ranked_port.append((1, {
                    "category": "PATTERN",
                    "text": f"{day_names[best_dow]}s consistently deliver your best prices — {pct_diff}% higher than other days over the last 90 days.",
                }))

    # --- Price volatility: species with big swings recently ---
    species_recent: dict[str, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg and hist_date in recent_dates[:5]:
            canonical = normalise_species(species)
            if canonical is None:
                continue
            species_recent[canonical].append(avg)

    for species, prices in species_recent.items():
        if len(prices) >= 3:
            pmin, pmax = min(prices), max(prices)
            if pmin > 0:
                volatility = ((pmax - pmin) / pmin) * 100
                if volatility > 15:
                    _ranked_port.append((2, {
                        "category": "VOLATILITY",
                        "text": f"{species} swung {volatility:.0f}% this week (£{pmin:.2f}–£{pmax:.2f}) — high volatility may signal changing supply or demand.",
                    }))
                    break

    # --- Species count trend ---
    species_by_date: dict[str, set] = defaultdict(set)
    for hist_date, species, *_ in history:
        canon = normalise_species(species)
        if canon is not None:
            species_by_date[hist_date].add(canon)
    if len(recent_dates) >= 3:
        recent_counts = [len(species_by_date.get(d, set())) for d in recent_dates[:3]]
        older_counts = [len(species_by_date.get(d, set())) for d in recent_dates[3:] if d in species_by_date]
        if older_counts:
            recent_avg = sum(recent_counts) / len(recent_counts)
            older_avg = sum(older_counts) / len(older_counts)
            if recent_avg > older_avg + 2:
                _ranked_port.append((3, {
                    "category": "GROWTH",
                    "text": f"You're listing more species recently — averaging {recent_avg:.0f} per session vs {older_avg:.0f} earlier this month.",
                }))
            elif older_avg > recent_avg + 2:
                _ranked_port.append((3, {
                    "category": "WATCH",
                    "text": f"Species count has dropped — {recent_avg:.0f} per session recently vs {older_avg:.0f} earlier. Worth checking if landings are diversifying elsewhere.",
                }))

    # --- Highest-value species this port: which species earns the most per kg? ---
    species_avg_30d: dict[str, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            canonical = normalise_species(species)
            if canonical is None:
                continue
            species_avg_30d[canonical].append(avg)
    if species_avg_30d:
        top_value = max(
            species_avg_30d.items(),
            key=lambda x: sum(x[1]) / len(x[1]),
        )
        top_sp, top_prices = top_value
        top_avg = sum(top_prices) / len(top_prices)
        _ranked_port.append((4, {
            "category": "STRENGTH",
            "text": f"{top_sp} is your highest-value species — averaging £{top_avg:.2f}/kg over the last 90 days.",
        }))

    # --- Price direction: is the port's overall average trending up or down? ---
    if len(recent_dates) >= 6:
        first_3 = recent_dates[:3]
        last_3 = recent_dates[3:6]
        first_prices = [
            avg for d, _, _, _, _, avg in history
            if d in first_3 and avg
        ]
        last_prices = [
            avg for d, _, _, _, _, avg in history
            if d in last_3 and avg
        ]
        if first_prices and last_prices:
            first_avg = sum(first_prices) / len(first_prices)
            last_avg = sum(last_prices) / len(last_prices)
            if last_avg > 0:
                trend_pct = ((first_avg - last_avg) / last_avg) * 100
                if abs(trend_pct) > 3:
                    direction = "up" if trend_pct > 0 else "down"
                    _ranked_port.append((5, {
                        "category": "TREND",
                        "text": f"Your overall average is trending {direction} — £{first_avg:.2f}/kg in the last 3 sessions vs £{last_avg:.2f} the 3 before that ({'+' if trend_pct > 0 else ''}{trend_pct:.1f}%).",
                    }))

    # === MARKET INTELLIGENCE — this port vs the market ===

    # --- Best performer vs market today ---
    best_today = None
    best_vs = -999
    for item in today_data:
        if item["position"] and item["position"]["vs_pct"] > best_vs:
            best_vs = item["position"]["vs_pct"]
            best_today = item
    if best_today and best_vs > 3:
        _ranked_market.append((1, {
            "category": "STRENGTH",
            "text": f"{best_today['species']} outperformed the UK average by {best_vs:.1f}% today — your strongest species against the market.",
        }))

    # --- Worst performer vs market today ---
    worst_today = None
    worst_vs = 999
    for item in today_data:
        if item["position"] and item["position"]["vs_pct"] < worst_vs:
            worst_vs = item["position"]["vs_pct"]
            worst_today = item
    if worst_today and worst_vs < -5:
        _ranked_market.append((4, {
            "category": "WATCH",
            "text": f"{worst_today['species']} came in {abs(worst_vs):.1f}% below the UK average today — worth checking grade mix or timing.",
        }))

    # --- Consistent outperformer: species beating market 20+ of last 30 days ---
    species_above_30d: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    last_30_dates = [d for d in recent_dates if len(recent_dates) <= 30 or d >= recent_dates[29]]
    for hist_date in last_30_dates:
        day_market = get_market_averages_for_date(hist_date)
        for h_date, species, _grade, _low, _high, avg in history:
            if h_date == hist_date and avg:
                canonical = normalise_species(species)
                if canonical is None:
                    continue
                mkt = day_market.get(canonical, {})
                if mkt.get("avg") and mkt["avg"] > 0:
                    above, total = species_above_30d[canonical]
                    total += 1
                    if avg > mkt["avg"]:
                        above += 1
                    species_above_30d[canonical] = (above, total)

    best_consistent = None
    best_consistency = 0
    for sp, (above, total) in species_above_30d.items():
        if total >= 15 and above >= 20 and above > best_consistency:
            best_consistent = sp
            best_consistency = above

    if best_consistent:
        above, total = species_above_30d[best_consistent]
        _ranked_market.append((2, {
            "category": "STRENGTH",
            "text": f"{best_consistent} is your most reliable market-beater — above UK average on {above} of the last {total} trading days.",
        }))

    # --- Best species vs market this week ---
    week_dates = recent_dates[:5]
    species_week_spread: dict[str, list[float]] = defaultdict(list)
    for hist_date in week_dates:
        day_market = get_market_averages_for_date(hist_date)
        for h_date, species, _grade, _low, _high, avg in history:
            if h_date == hist_date and avg:
                canonical = normalise_species(species)
                if canonical is None:
                    continue
                mkt = day_market.get(canonical, {})
                if mkt.get("avg") and mkt["avg"] > 0:
                    spread = ((avg - mkt["avg"]) / mkt["avg"]) * 100
                    species_week_spread[canonical].append(spread)

    best_week_sp = None
    best_week_avg = -999
    for sp, spreads in species_week_spread.items():
        if len(spreads) >= 2:
            avg_spread = sum(spreads) / len(spreads)
            if avg_spread > best_week_avg:
                best_week_avg = avg_spread
                best_week_sp = sp

    if best_week_sp and best_week_avg > 3:
        _ranked_market.append((3, {
            "category": "STRENGTH",
            "text": f"{best_week_sp} had the widest margin over market this week — averaging +{best_week_avg:.1f}% across {len(species_week_spread[best_week_sp])} sessions.",
        }))

    # --- Species below market for multiple days ---
    species_below_streak: dict[str, int] = defaultdict(int)
    for hist_date in recent_dates[:5]:
        day_market = get_market_averages_for_date(hist_date)
        for h_date, species, _grade, _low, _high, avg in history:
            if h_date == hist_date and avg:
                canonical = normalise_species(species)
                if canonical is None:
                    continue
                mkt = day_market.get(canonical, {})
                if mkt.get("avg") and avg < mkt["avg"] * 0.95:
                    species_below_streak[canonical] += 1

    for species, count in species_below_streak.items():
        if count >= 3:
            _ranked_market.append((5, {
                "category": "WATCH",
                "text": f"{species} has traded below market for {count} of the last 5 sessions — consider whether grade distribution or volumes are affecting price.",
            }))
            break

    # --- Overall market position ---
    all_today_prices = [info["avg"] for info in market.values() if info.get("avg")]
    if all_today_prices:
        market_avg_today = sum(all_today_prices) / len(all_today_prices)
        port_avg = sum(
            item["price_avg"] for item in today_data if item["price_avg"]
        ) / max(1, len([i for i in today_data if i["price_avg"]]))
        if port_avg > market_avg_today * 1.05:
            pct_above = ((port_avg - market_avg_today) / market_avg_today) * 100
            _ranked_market.append((6, {
                "category": "POSITION",
                "text": f"Your average today (£{port_avg:.2f}/kg) is {pct_above:.0f}% above the UK-wide average — a strong position for attracting landings.",
            }))
        elif port_avg < market_avg_today * 0.95:
            pct_below = ((market_avg_today - port_avg) / market_avg_today) * 100
            _ranked_market.append((6, {
                "category": "POSITION",
                "text": f"Your average today (£{port_avg:.2f}/kg) is {pct_below:.0f}% below the UK-wide average — worth reviewing whether grade mix or species composition is a factor.",
            }))

    # --- Missing opportunity: species in market but not at this port ---
    port_species = {item["species"] for item in today_data}
    for species, info in market.items():
        canonical = normalise_species(species)
        if canonical is None:
            continue
        if canonical not in port_species and info["port_count"] >= 2 and info["avg"] > 5.0:
            _ranked_market.append((7, {
                "category": "OPPORTUNITY",
                "text": f"{canonical} traded at £{info['avg']:.2f} across {info['port_count']} ports today — a gap in your listings worth investigating.",
            }))

    # --- Biggest spread in market ---
    max_spread_species = None
    max_spread_pct = 0
    for species, info in market.items():
        if info["port_count"] >= 2 and info["min"] > 0:
            spread_pct = ((info["max"] - info["min"]) / info["min"]) * 100
            if spread_pct > max_spread_pct:
                max_spread_pct = spread_pct
                max_spread_species = normalise_species(species)
    if max_spread_species and max_spread_pct > 15:
        _ranked_market.append((8, {
            "category": "SPREAD",
            "text": f"{max_spread_species} has the widest UK spread today at {max_spread_pct:.0f}% — buyers looking for value may shift to cheaper ports.",
        }))

    # Sort by priority and cap at 3 each
    _ranked_port.sort(key=lambda x: x[0])
    _ranked_market.sort(key=lambda x: x[0])

    # Period classification by priority rank
    _PORT_PERIOD = {1: "month", 2: "week", 3: "week", 4: "month", 5: "week"}
    _MKT_PERIOD = {1: "today", 2: "month", 3: "week", 4: "today", 5: "week",
                   6: "today", 7: "today", 8: "today"}

    return {
        "port": [
            {**item, "period": _PORT_PERIOD.get(pri, "week")}
            for pri, item in _ranked_port[:3]
        ],
        "market": [
            {**item, "period": _MKT_PERIOD.get(pri, "today")}
            for pri, item in _ranked_market[:3]
        ],
    }


def build_category_stats(
    today_data: list[dict],
    last_week_prices: dict,
    market: dict,
    history: list[tuple],
) -> dict:
    """Compute per-category hero stats for the category pill filter."""
    _CATEGORIES = ["all", "demersal", "flatfish", "shellfish", "pelagic", "other"]

    # Build history date buckets for week/month rolling windows
    date_cat_prices: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            canonical = normalise_species(species)
            if canonical is None:
                continue
            cat = get_species_category(canonical)
            date_cat_prices[hist_date]["all"].append(avg)
            date_cat_prices[hist_date][cat].append(avg)

    sorted_dates = sorted(date_cat_prices.keys(), reverse=True)
    this_week_dates = sorted_dates[:5]
    last_week_dates = sorted_dates[5:10]
    this_month_dates = sorted_dates[:20]
    last_month_dates = sorted_dates[20:40]

    def _period_avg(dates: list[str], cat: str) -> float | None:
        prices = [p for d in dates for p in date_cat_prices.get(d, {}).get(cat, [])]
        return round(sum(prices) / len(prices), 2) if prices else None

    # Build last_week raw-species -> category mapping from today_data
    raw_to_cat = {item["raw_species"]: item["category"] for item in today_data}

    result = {}
    for cat in _CATEGORIES:
        # Today's avg for this category
        today_prices = [
            item["price_avg"] for item in today_data
            if item["price_avg"] and (cat == "all" or item["category"] == cat)
        ]
        today_avg = round(sum(today_prices) / len(today_prices), 2) if today_prices else None

        # vs last week: match last-week species to category using raw_to_cat
        lw_prices_cat = [
            v["price_avg"] for (sp, _gr), v in last_week_prices.items()
            if v["price_avg"] and (
                cat == "all" or
                raw_to_cat.get(sp, get_species_category(normalise_species(sp))) == cat
            )
        ]
        vs_last_week = None
        last_week_price = None
        if lw_prices_cat and today_prices:
            lw_avg = sum(lw_prices_cat) / len(lw_prices_cat)
            td_avg = sum(today_prices) / len(today_prices)
            if lw_avg > 0:
                vs_last_week = round(((td_avg - lw_avg) / lw_avg) * 100, 1)
            last_week_price = round(lw_avg, 2)

        # vs UK market: filter market to species in this category
        port_species_in_cat = {item["species"] for item in today_data if cat == "all" or item["category"] == cat}
        mkt_avgs = [
            info["avg"] for sp, info in market.items()
            if info.get("avg") and sp in port_species_in_cat
        ]
        vs_market = None
        if mkt_avgs and today_prices:
            mkt_overall = sum(mkt_avgs) / len(mkt_avgs)
            port_overall = sum(today_prices) / len(today_prices)
            if mkt_overall > 0:
                vs_market = round(((port_overall - mkt_overall) / mkt_overall) * 100, 1)

        # Rolling week/month averages from history
        this_week_avg = _period_avg(this_week_dates, cat)
        prev_week_avg = _period_avg(last_week_dates, cat)
        week_change = None
        if this_week_avg and prev_week_avg and prev_week_avg > 0:
            week_change = round(((this_week_avg - prev_week_avg) / prev_week_avg) * 100, 1)

        this_month_avg = _period_avg(this_month_dates, cat)
        prev_month_avg = _period_avg(last_month_dates, cat)
        month_change = None
        if this_month_avg and prev_month_avg and prev_month_avg > 0:
            month_change = round(((this_month_avg - prev_month_avg) / prev_month_avg) * 100, 1)

        result[cat] = {
            "today_avg": today_avg,
            "vs_last_week": vs_last_week,
            "last_week_price": last_week_price,
            "vs_market": vs_market,
            "week_avg": this_week_avg,
            "week_change": week_change,
            "month_avg": this_month_avg,
            "month_change": month_change,
        }

    return result


def build_performance_overview(
    port_name: str, date: str, history: list[tuple], market: dict,
) -> dict:
    """Build week-over-week and month-over-month performance metrics."""
    # Group history by date -> list of avg prices
    date_prices: dict[str, list[float]] = defaultdict(list)
    for hist_date, species, _grade, _low, _high, avg in history:
        if avg:
            date_prices[hist_date].append(avg)

    sorted_dates = sorted(date_prices.keys(), reverse=True)

    # Split into this week (last 5 trading days) and last week (5 before that)
    this_week_dates = sorted_dates[:5]
    last_week_dates = sorted_dates[5:10]

    def _period_avg(dates: list[str]) -> float | None:
        prices = [p for d in dates for p in date_prices.get(d, [])]
        return round(sum(prices) / len(prices), 2) if prices else None

    this_week_avg = _period_avg(this_week_dates)
    last_week_avg = _period_avg(last_week_dates)

    week_change = None
    if this_week_avg and last_week_avg and last_week_avg > 0:
        week_change = round(((this_week_avg - last_week_avg) / last_week_avg) * 100, 1)

    # Month-over-month: last 20 trading days vs 20 before that
    this_month_dates = sorted_dates[:20]
    last_month_dates = sorted_dates[20:40]

    this_month_avg = _period_avg(this_month_dates)
    last_month_avg = _period_avg(last_month_dates)

    month_change = None
    if this_month_avg and last_month_avg and last_month_avg > 0:
        month_change = round(((this_month_avg - last_month_avg) / last_month_avg) * 100, 1)

    # Market position trend: avg vs-market % this week vs last week
    def _market_position(dates: list[str]) -> float | None:
        vs_pcts = []
        for d in dates:
            day_market = get_market_averages_for_date(d)
            for h_date, species, _grade, _low, _high, avg in history:
                if h_date == d and avg:
                    canonical = normalise_species(species)
                    if canonical is None:
                        continue
                    mkt = day_market.get(canonical, {})
                    if mkt.get("avg") and mkt["avg"] > 0:
                        vs_pcts.append(((avg - mkt["avg"]) / mkt["avg"]) * 100)
        return round(sum(vs_pcts) / len(vs_pcts), 1) if vs_pcts else None

    mkt_pos_this_week = _market_position(this_week_dates)
    mkt_pos_last_week = _market_position(last_week_dates)

    mkt_trend = None
    if mkt_pos_this_week is not None and mkt_pos_last_week is not None:
        mkt_trend = round(mkt_pos_this_week - mkt_pos_last_week, 1)

    # Species count trend
    this_week_species = set()
    last_week_species = set()
    for d in this_week_dates:
        for h_date, species, *_ in history:
            if h_date == d:
                canon = normalise_species(species)
                if canon is not None:
                    this_week_species.add(canon)
    for d in last_week_dates:
        for h_date, species, *_ in history:
            if h_date == d:
                canon = normalise_species(species)
                if canon is not None:
                    last_week_species.add(canon)

    # Trading sessions this week vs last
    sessions_this_week = len(this_week_dates)
    sessions_last_week = len(last_week_dates)

    # Volume (boxes) from landings table if available
    conn = get_connection()

    def _boxes_for_dates(dates: list[str]) -> int | None:
        if not dates:
            return None
        placeholders = ",".join("?" for _ in dates)
        try:
            row = conn.execute(
                f"""SELECT SUM(boxes) FROM landings
                    WHERE port = ? AND date IN ({placeholders})""",
                [port_name] + dates,
            ).fetchone()
            return row[0] if row and row[0] else None
        except sqlite3.OperationalError:
            return None

    total_boxes = _boxes_for_dates(this_week_dates)
    last_week_boxes = _boxes_for_dates(last_week_dates)
    conn.close()

    boxes_change = None
    if total_boxes and last_week_boxes and last_week_boxes > 0:
        boxes_change = round(((total_boxes - last_week_boxes) / last_week_boxes) * 100, 1)

    return {
        "this_week_avg": this_week_avg,
        "last_week_avg": last_week_avg,
        "week_change": week_change,
        "this_month_avg": this_month_avg,
        "last_month_avg": last_month_avg,
        "month_change": month_change,
        "mkt_pos_this_week": mkt_pos_this_week,
        "mkt_pos_last_week": mkt_pos_last_week,
        "mkt_trend": mkt_trend,
        "species_this_week": len(this_week_species),
        "species_last_week": len(last_week_species),
        "sessions_this_week": sessions_this_week,
        "sessions_last_week": sessions_last_week,
        "total_boxes": total_boxes,
        "last_week_boxes": last_week_boxes,
        "boxes_change": boxes_change,
    }


def time_ago(dt_str: str | None) -> str | None:
    """Return a human-readable 'X mins ago' string for a datetime string."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        mins = int((datetime.now() - dt).total_seconds() / 60)
        if mins < 1:
            return "just now"
        elif mins < 60:
            return f"{mins} min{'s' if mins != 1 else ''} ago"
        elif mins < 60 * 24:
            hours = mins // 60
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            return dt.strftime("%-d %b at %H:%M")
    except (ValueError, TypeError):
        return dt_str


def build_scrape_info_display(scrape_info: dict) -> dict:
    """Format scrape_info timestamps as human-readable strings for templates."""
    return {
        "last_checked_ago": time_ago(scrape_info.get("last_checked")),
        "last_received_ago": time_ago(scrape_info.get("last_received")),
        "last_checked": scrape_info.get("last_checked"),
        "last_received": scrape_info.get("last_received"),
    }


def format_data_freshness(scraped_at: str | None, auction_date: str) -> dict:
    """Return a dict describing how fresh the data is for display in the header."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    if not scraped_at:
        return {"label": "No data", "status": "stale", "tooltip": "No data available"}

    try:
        if "T" in scraped_at:
            scraped_dt = datetime.fromisoformat(scraped_at)
        else:
            scraped_dt = datetime.strptime(scraped_at, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {"label": "Data available", "status": "recent", "tooltip": scraped_at}

    hours_ago = (now - scraped_dt).total_seconds() / 3600

    if auction_date == today_str:
        if hours_ago < 1:
            label = f"Updated {int((now - scraped_dt).total_seconds() / 60)}m ago"
            status = "live"
        elif hours_ago < 12:
            label = f"Updated {scraped_dt.strftime('%H:%M')} today"
            status = "live"
        else:
            label = f"Today's data · scraped {scraped_dt.strftime('%H:%M')}"
            status = "live"
        tooltip = f"Data last updated {scraped_dt.strftime('%-d %b %Y at %H:%M')}"
    elif hours_ago < 48:
        label = f"Yesterday's auction · {scraped_dt.strftime('%H:%M')}"
        status = "recent"
        tooltip = f"Last updated {scraped_dt.strftime('%-d %b %Y at %H:%M')}"
    else:
        days_ago = int(hours_ago / 24)
        label = f"{days_ago}d old · {auction_date}"
        status = "stale"
        tooltip = f"Data from {auction_date}, last updated {scraped_dt.strftime('%-d %b %Y at %H:%M')}"

    return {"label": label, "status": status, "tooltip": tooltip}


def parse_form_prices(form, port_name: str, date: str) -> list[PriceRecord]:
    """Parse price rows from a web form submission."""
    records = []
    now = datetime.now().isoformat()

    i = 0
    while f"species_{i}" in form:
        species = form.get(f"species_{i}", "").strip()
        if not species:
            i += 1
            continue

        grade = form.get(f"grade_{i}", "").strip()
        low = form_float(form.get(f"low_{i}"))
        high = form_float(form.get(f"high_{i}"))
        avg = form_float(form.get(f"avg_{i}"))

        if avg is None and low is not None and high is not None:
            avg = round((low + high) / 2, 2)

        if avg is None and low is None and high is None:
            i += 1
            continue

        records.append(PriceRecord(
            date=date, port=port_name, species=species, grade=grade,
            price_low=low, price_high=high, price_avg=avg, scraped_at=now,
        ))
        i += 1

    return records


def form_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    cleaned = val.strip().lstrip("£$€").strip()
    try:
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Phase 0: New shared infrastructure for dashboard redesign
# ---------------------------------------------------------------------------


def build_competitive_market(port_name: str, date: str) -> list[dict]:
    """Per-species competitive position using only ports that share each species.

    For each species at the given port, finds other ports selling that same
    species today and calculates a like-for-like market average. This is fairer
    than the full-market average because it only compares against ports in the
    same fishery for each species.

    "Top-grade average" = MAX(price_avg) across grades per port per species,
    consistent with get_market_averages_for_date().
    """
    all_rows = get_all_prices_for_date(date)

    # Group by (canonical_species, port) -> best grade data + all grades
    # Also track per-port data capabilities
    species_port_best: dict[str, dict[str, float]] = defaultdict(dict)
    species_port_grades: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    port_data: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))

    for row in all_rows:
        _, port, raw_species, grade, low, high, avg, weight_kg, boxes = row
        canonical = normalise_species(raw_species)
        if canonical is None:
            continue

        grade_info = {
            "grade": grade,
            "price_low": low,
            "price_high": high,
            "price_avg": avg,
            "weight_kg": weight_kg,
            "boxes": boxes,
        }
        species_port_grades[canonical][port].append(grade_info)

        # Track best (highest avg) per port per species
        if avg and (canonical not in species_port_best or
                    port not in species_port_best[canonical] or
                    avg > species_port_best[canonical][port]):
            species_port_best[canonical][port] = avg

        # Track data capabilities per port per species
        key = port_data[canonical][port]
        if weight_kg and weight_kg > 0:
            key["has_volume"] = True
        if low is not None:
            key["has_ranges"] = True
        if boxes is not None and boxes > 0:
            key["has_boxes"] = True

    # Build port code lookup
    from quayside.db import get_all_ports
    all_ports = get_all_ports()
    port_code_map = {p["name"]: p.get("code", "") for p in all_ports if p.get("data_method") != "demo"}

    result = []
    for species, port_prices in species_port_best.items():
        if port_name not in port_prices:
            continue  # This species isn't at our port

        port_avg = port_prices[port_name]
        if not port_avg:
            continue

        # Comparison ports: everyone else with this species
        comparison_ports = []
        other_prices = []
        for other_port, other_avg in port_prices.items():
            if other_port == port_name:
                continue
            other_prices.append(other_avg)
            # Summarise grades for comparison port
            other_grades = species_port_grades[species].get(other_port, [])
            grades_summary = ", ".join(
                sorted({g["grade"] for g in other_grades if g["grade"]})
            )
            total_weight = sum(g.get("weight_kg") or 0 for g in other_grades)
            comparison_ports.append({
                "port_name": other_port,
                "port_code": port_code_map.get(other_port, ""),
                "price_avg": round(other_avg, 2),
                "weight_kg": round(total_weight, 1) if total_weight else None,
                "grades_summary": grades_summary,
            })

        is_only_port = len(other_prices) == 0
        if is_only_port:
            market_avg = None
            vs_market_pct = None
            is_best_uk = True
        else:
            market_avg = round(sum(other_prices) / len(other_prices), 2)
            vs_market_pct = round(((port_avg - market_avg) / market_avg) * 100, 1)
            is_best_uk = all(port_avg >= p for p in other_prices)

        # Port's own grade details
        port_grades = []
        for g in sorted(species_port_grades[species].get(port_name, []),
                        key=lambda x: x.get("price_avg") or 0, reverse=True):
            port_grades.append({
                "grade": g["grade"],
                "price_low": round(g["price_low"], 2) if g["price_low"] is not None else None,
                "price_high": round(g["price_high"], 2) if g["price_high"] is not None else None,
                "price_avg": round(g["price_avg"], 2) if g["price_avg"] is not None else None,
                "weight_kg": round(g["weight_kg"], 1) if g.get("weight_kg") else None,
                "boxes": g.get("boxes"),
            })

        # Data capability flags for this port's data on this species
        port_caps = port_data[species].get(port_name, {})

        result.append({
            "species": species,
            "category": get_species_category(species),
            "port_avg": round(port_avg, 2),
            "port_grades": port_grades,
            "market_avg": market_avg,
            "vs_market_pct": vs_market_pct,
            "comparison_ports": sorted(comparison_ports, key=lambda x: x["price_avg"], reverse=True),
            "is_best_uk": is_best_uk,
            "is_only_port": is_only_port,
            "port_has_volume": port_caps.get("has_volume", False),
            "port_has_ranges": port_caps.get("has_ranges", False),
            "port_has_boxes": port_caps.get("has_boxes", False),
        })

    # Sort: comparable species by vs_market_pct desc, then only-port species
    comparable = [r for r in result if not r["is_only_port"]]
    only_port = [r for r in result if r["is_only_port"]]
    comparable.sort(key=lambda x: x["vs_market_pct"] or 0, reverse=True)
    only_port.sort(key=lambda x: x["port_avg"], reverse=True)

    return comparable + only_port


def build_competitive_summary(competitive_data: list[dict]) -> dict:
    """Summary stats from competitive market data.

    Pure computation on the output of build_competitive_market().
    """
    comparable = [d for d in competitive_data if not d["is_only_port"]]
    best_uk = [d for d in competitive_data if d["is_best_uk"]]
    above = [d for d in comparable if (d["vs_market_pct"] or 0) > 0]
    below = [d for d in comparable if (d["vs_market_pct"] or 0) < 0]
    only_port = [d for d in competitive_data if d["is_only_port"]]

    # Like-for-like position: average vs_market_pct across comparable species
    if comparable:
        like_for_like_pct = round(
            sum(d["vs_market_pct"] for d in comparable) / len(comparable), 1
        )
    else:
        like_for_like_pct = None

    return {
        "best_uk_count": len(best_uk),
        "best_uk_species": [d["species"] for d in best_uk],
        "above_avg_count": len(above),
        "above_avg_species": [d["species"] for d in above],
        "below_avg_count": len(below),
        "below_avg_species": [d["species"] for d in below],
        "only_port_count": len(only_port),
        "comparable_count": len(comparable),
        "like_for_like_position_pct": like_for_like_pct,
    }


def build_smart_alerts(
    port_name: str,
    date: str,
    alert_type: str = "port",
) -> list[dict]:
    """Generate max 4 priority-sorted alert cards for a port dashboard.

    Alert types (port mode):
    1. Species >15% below competitive market today (severity: warning)
    2. Species where this port is best UK price 10+ of last 20 sessions (severity: strength)
    3. Species with >20% price swing vs yesterday (severity: spike)
    4. Species count dropped significantly vs rolling average (severity: watch)

    Returns list of {type, severity, headline, detail, species, port}.
    """
    alerts: list[tuple[int, dict]] = []  # (priority, alert_dict)

    # ---- Alert 1: Species significantly below competitive market ----
    all_rows = get_all_prices_for_date(date)
    # Build per-species, per-port best prices (same logic as build_competitive_market)
    species_port_best: dict[str, dict[str, float]] = defaultdict(dict)
    for row in all_rows:
        _, port, raw_species, _grade, _low, _high, avg, _wt, _bx = row
        canonical = normalise_species(raw_species)
        if canonical is None:
            continue
        if avg and (canonical not in species_port_best or
                    port not in species_port_best[canonical] or
                    avg > species_port_best[canonical][port]):
            species_port_best[canonical][port] = avg

    below_market_species = []
    for species, port_prices in species_port_best.items():
        if port_name not in port_prices:
            continue
        port_avg = port_prices[port_name]
        others = [v for k, v in port_prices.items() if k != port_name]
        if not others:
            continue
        market_avg = sum(others) / len(others)
        if market_avg > 0:
            vs_pct = ((port_avg - market_avg) / market_avg) * 100
            if vs_pct < -15:
                below_market_species.append((species, round(vs_pct, 1)))

    if below_market_species:
        below_market_species.sort(key=lambda x: x[1])
        worst = below_market_species[0]
        alerts.append((1, {
            "type": "below_market",
            "severity": "warning",
            "headline": f"{worst[0]} is {abs(worst[1])}% below your competitive market",
            "detail": f"Your top-grade average is significantly below other ports selling {worst[0]} today. Check grade mix or timing.",
            "species": worst[0],
            "port": port_name,
        }))

    # ---- Alert 2: Best UK price streak (10+ of last 20 sessions) ----
    recent_dates = get_trading_dates_recent(20)
    if len(recent_dates) >= 5:
        oldest = recent_dates[-1]
        range_rows = get_prices_for_date_range(oldest, date)

        # Group by (date, species, port) -> best avg
        hist_best: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
        for r_date, r_port, r_species, _grade, _low, _high, r_avg in range_rows:
            canonical = normalise_species(r_species)
            if canonical is None or not r_avg:
                continue
            if (canonical not in hist_best[r_date] or
                    r_port not in hist_best[r_date][canonical] or
                    r_avg > hist_best[r_date][canonical][r_port]):
                hist_best[r_date][canonical][r_port] = r_avg

        # Count how many sessions this port was best UK for each species
        species_best_count: dict[str, int] = defaultdict(int)
        species_session_count: dict[str, int] = defaultdict(int)
        for d in recent_dates:
            for species, port_prices in hist_best.get(d, {}).items():
                if port_name not in port_prices:
                    continue
                species_session_count[species] += 1
                our_price = port_prices[port_name]
                if all(our_price >= v for v in port_prices.values()):
                    species_best_count[species] += 1

        best_streakers = [
            (sp, cnt, species_session_count[sp])
            for sp, cnt in species_best_count.items()
            if cnt >= 10 and species_session_count[sp] >= 15
        ]
        if best_streakers:
            best_streakers.sort(key=lambda x: x[1], reverse=True)
            top = best_streakers[0]
            alerts.append((2, {
                "type": "best_uk_streak",
                "severity": "strength",
                "headline": f"Best UK price for {top[0]} — {top[1]} of last {top[2]} sessions",
                "detail": f"You've consistently offered the best top-grade price for {top[0]}. A strength to promote to vessel skippers.",
                "species": top[0],
                "port": port_name,
            }))

    # ---- Alert 3: Price swing >20% vs yesterday ----
    prev_date = get_previous_date(date)
    if prev_date:
        prev_rows = get_all_prices_for_date(prev_date)
        prev_best: dict[str, dict[str, float]] = defaultdict(dict)
        for row in prev_rows:
            _, port, raw_species, _grade, _low, _high, avg, _wt, _bx = row
            canonical = normalise_species(raw_species)
            if canonical is None or not avg:
                continue
            if (canonical not in prev_best or
                    port not in prev_best[canonical] or
                    avg > prev_best[canonical][port]):
                prev_best[canonical][port] = avg

        swing_species = []
        for species, port_prices in species_port_best.items():
            if port_name not in port_prices:
                continue
            today_price = port_prices[port_name]
            yesterday_price = prev_best.get(species, {}).get(port_name)
            if yesterday_price and yesterday_price > 0:
                swing_pct = ((today_price - yesterday_price) / yesterday_price) * 100
                if abs(swing_pct) > 20:
                    swing_species.append((species, round(swing_pct, 1)))

        if swing_species:
            swing_species.sort(key=lambda x: abs(x[1]), reverse=True)
            top_swing = swing_species[0]
            direction = "up" if top_swing[1] > 0 else "down"
            alerts.append((3, {
                "type": "price_swing",
                "severity": "spike",
                "headline": f"{top_swing[0]} swung {abs(top_swing[1])}% {direction} vs yesterday",
                "detail": f"Unusual daily movement. {'Strong demand or tight supply.' if direction == 'up' else 'Check if grade mix changed or supply increased.'}",
                "species": top_swing[0],
                "port": port_name,
            }))

    # ---- Alert 4: Species count drop vs rolling average ----
    if len(recent_dates) >= 5:
        # Count species per date at this port from the range data we already have
        port_species_by_date: dict[str, set[str]] = defaultdict(set)
        for r_date, r_port, r_species, _grade, _low, _high, r_avg in range_rows:
            if r_port == port_name and r_avg:
                canonical = normalise_species(r_species)
                if canonical:
                    port_species_by_date[r_date].add(canonical)

        today_count = len(port_species_by_date.get(date, set()))
        historical_counts = [
            len(port_species_by_date.get(d, set()))
            for d in recent_dates[1:] if d in port_species_by_date
        ]
        if historical_counts:
            avg_count = sum(historical_counts) / len(historical_counts)
            if avg_count > 0 and today_count < avg_count * 0.7:
                alerts.append((4, {
                    "type": "species_drop",
                    "severity": "watch",
                    "headline": f"Only {today_count} species today vs {avg_count:.0f} average",
                    "detail": "Species count is significantly below your recent average. May indicate fewer landings or vessels.",
                    "species": None,
                    "port": port_name,
                }))

    # Sort by priority, cap at 4
    alerts.sort(key=lambda x: x[0])
    result = [a[1] for a in alerts[:4]]

    # If no alerts, return a calm message
    if not result:
        result = [{
            "type": "calm",
            "severity": "calm",
            "headline": "Your auction tracked normally today",
            "detail": "No unusual price movements, species count is stable, and your market position is within normal range.",
            "species": None,
            "port": port_name,
        }]

    return result


def build_missing_species(port_name: str, date: str) -> list[dict]:
    """Species trading at other ports today but not at this port.

    Filtered by port similarity (shares at least 2 species) and minimum
    price threshold (>£2/kg) to exclude low-value bycatch.

    Returns list of {species, category, best_price, best_port, total_volume, port_count}.
    """
    all_rows = get_all_prices_for_date(date)

    # Group by canonical species -> {port: best_avg, total_weight}
    species_ports: dict[str, dict[str, float]] = defaultdict(dict)
    species_volume: dict[str, float] = defaultdict(float)

    for row in all_rows:
        _, port, raw_species, _grade, _low, _high, avg, weight_kg, _boxes = row
        canonical = normalise_species(raw_species)
        if canonical is None:
            continue

        if avg and (canonical not in species_ports or
                    port not in species_ports[canonical] or
                    avg > species_ports[canonical][port]):
            species_ports[canonical][port] = avg
        if weight_kg:
            species_volume[canonical] += weight_kg

    # This port's species set
    our_species = {sp for sp, ports in species_ports.items() if port_name in ports}

    # Find species NOT at our port
    missing = []
    for species, port_prices in species_ports.items():
        if species in our_species:
            continue

        # Filter: port similarity — at least one comparison port must share 2+ species with us
        comparison_ports = set(port_prices.keys())
        has_similar_port = False
        for other_port in comparison_ports:
            other_species = {sp for sp, pp in species_ports.items() if other_port in pp}
            shared = our_species & other_species
            if len(shared) >= 2:
                has_similar_port = True
                break
        if not has_similar_port:
            continue

        # Price threshold
        best_port = max(port_prices, key=port_prices.get)
        best_price = port_prices[best_port]
        if best_price < 2.0:
            continue

        missing.append({
            "species": species,
            "category": get_species_category(species),
            "best_price": round(best_price, 2),
            "best_port": best_port,
            "total_volume": round(species_volume.get(species, 0), 1) or None,
            "port_count": len(port_prices),
        })

    # Sort by best price descending, cap at 10
    missing.sort(key=lambda x: x["best_price"], reverse=True)
    return missing[:10]
