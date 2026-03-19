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
    boxes: int | None = None  # number of boxes/lots sold (Scrabster)
    defra_code: str | None = None  # 3-letter DEFRA/MMO species code (Brixham)
    week_avg: float | None = None  # rolling weekly average price £/kg (Brixham)
    size_band: str | None = None  # size descriptor e.g. "801g+", "0.5-0.7Kg" (Newlyn)


@dataclass
class LandingRecord:
    date: str  # YYYY-MM-DD
    port: str
    vessel_name: str
    vessel_code: str
    species: str
    boxes: int
    boxes_msc: int
    scraped_at: str  # ISO timestamp
