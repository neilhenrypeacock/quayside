from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PriceRecord:
    date: str  # YYYY-MM-DD
    port: str
    species: str
    grade: str  # A1, A2, A3, A4, A5, A4-Chipper, etc.
    price_low: float | None
    price_high: float | None
    price_avg: float | None
    scraped_at: str  # ISO timestamp
    weight_kg: float | None = None  # weight sold in kg (None if not published by port)
