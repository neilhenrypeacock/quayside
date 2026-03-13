from __future__ import annotations

from dataclasses import dataclass


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


LANDING_SPECIES = [
    "Cod",
    "Monks",
    "Haddock Lrg/Med",
    "Haddock Sml",
    "Haddock Sml Round",
    "Whiting",
    "Whiting Round",
    "Saithe",
    "Megrim",
    "Squid",
    "Hake",
    "Lemons",
    "Plaice",
    "Witches",
    "Ling",
    "Others",
]
