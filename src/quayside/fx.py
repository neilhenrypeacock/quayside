"""Fetch GBP/EUR exchange rate from the Frankfurter API.

Frankfurter (frankfurter.dev) is a free, open-source API for current and
historical foreign exchange rates published by the European Central Bank.

Used in the daily digest to show the EUR/GBP rate, which directly impacts
export prices for UK-landed fish sold into European markets.
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.frankfurter.dev/v1"


def get_rate(
    base: str = "GBP",
    target: str = "EUR",
    date: str | None = None,
) -> dict | None:
    """Fetch exchange rate for a given date (YYYY-MM-DD) or latest.

    Returns dict with keys: 'rate', 'date', 'base', 'target'
    or None on failure.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # Try specific date first, fall back to latest
    url = f"{API_BASE}/{date}?base={base}&symbols={target}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Could not fetch exchange rate: %s", e)
        return None
    except (ValueError, KeyError) as e:
        logger.warning("Could not parse exchange rate response: %s", e)
        return None

    rate = data.get("rates", {}).get(target)
    if rate is None:
        # Date might be a weekend/holiday — try latest
        try:
            resp = requests.get(
                f"{API_BASE}/latest?base={base}&symbols={target}", timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            rate = data.get("rates", {}).get(target)
        except requests.RequestException:
            return None

    if rate is None:
        return None

    return {
        "rate": round(rate, 4),
        "date": data.get("date", date),
        "base": base,
        "target": target,
    }
