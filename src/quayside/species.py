"""Species name normalisation for cross-port comparison.

Raw species names differ between ports (e.g. "Monks" at Peterhead, "Monk" at Brixham,
"Monk Or Anglers" at Newlyn). This module maps them to canonical display names.

The mapping is applied at **report time only** — the database stores raw names as
scraped, preserving the source exactly. This module is used by report.py when
building cross-port comparisons.
"""

from __future__ import annotations

# Canonical name → list of raw names found across ports.
# Keep alphabetical by canonical name. Add new entries as new ports are added.
_CANONICAL_MAP: dict[str, list[str]] = {
    "Black Bream": ["Black Bream", "Bream"],
    "Brill": ["Brill"],
    "Catfish": ["Catfish Scottish", "Catfish"],
    "Cod": ["Cod"],
    "Coley (Saithe)": ["Coley", "Saithe", "Saithe, Coal Fish"],
    "Conger Eel": ["Conger", "Conger Eels"],
    "Cuttlefish": ["Cuttlefish"],
    "Dab": ["Dab"],
    "Dover Sole": ["Sole", "Dover Sole"],
    "Flounder": ["Flounder"],
    "Gurnard": ["Gurnard", "Gurnard and Latchet"],
    "Dogfish": ["Dogfish"],
    "Haddock": ["Haddock", "Haddock Round"],
    "Hake": ["Hake", "MSC Hake"],
    "Halibut": ["Halibut"],
    "John Dory": ["Dory", "John Dory"],
    "Lemon Sole": ["Lemons", "Lem", "Lemon Sole"],
    "Ling": ["Ling"],
    "Lobster": ["Lobster"],
    "Mackerel": ["Mackerel"],
    "Megrim": ["Megrim"],
    "Monkfish": ["Monks", "Monk", "Monk Or Anglers"],
    "Octopus": ["Octopus", "Mediterranean Octopus Pot Caught"],
    "Plaice": ["Plaice"],
    "Pollack": ["Lythe/Pollack", "Pollack", "Pollack, Lythe"],
    "Prawns": ["Prawns"],
    "Red Mullet": ["Mulred", "Red Mullet"],
    "Sand Sole": ["Sandsol1", "Sandsol2", "Sand Sole"],
    "Scad": ["Scad/Horse", "Scad SCAD"],
    "Skate": ["Skate", "Skate Medium", "Skate Round", "Skate Small"],
    "Smoothhound": ["Smhound", "Smoothhound"],
    "Spurdog": ["Spurdog"],
    "Squid": ["Squid"],
    "Turbot": ["Turbot"],
    "Weaver": ["Weaver"],
    "Whiting": ["Whiting", "Whiting Round"],
    "Witch": ["Witches", "Witch"],
}

# Build reverse lookup: raw_name (case-insensitive) → canonical name
_RAW_TO_CANONICAL: dict[str, str] = {}
for canonical, raw_names in _CANONICAL_MAP.items():
    for raw in raw_names:
        _RAW_TO_CANONICAL[raw.lower()] = canonical


def normalise_species(raw_name: str) -> str:
    """Return the canonical species name for a raw scraped name.

    If no mapping exists, returns the raw name unchanged (title-cased).
    This means unmapped species still appear in the report — they just
    won't merge with other ports' names.
    """
    canonical = _RAW_TO_CANONICAL.get(raw_name.lower())
    if canonical:
        return canonical
    # Fall back to title-casing the raw name for display
    return raw_name.strip().title()


def get_all_canonical_names() -> list[str]:
    """Return sorted list of all canonical species names."""
    return sorted(_CANONICAL_MAP.keys())


# Category groupings for canonical species names.
# Categories: "demersal", "flatfish", "shellfish", "pelagic", "other"
_CATEGORY_MAP: dict[str, str] = {
    "Black Bream": "other",
    "Brill": "flatfish",
    "Catfish": "demersal",
    "Cod": "demersal",
    "Coley (Saithe)": "demersal",
    "Conger Eel": "demersal",
    "Cuttlefish": "other",
    "Dab": "flatfish",
    "Dogfish": "other",
    "Dover Sole": "flatfish",
    "Flounder": "flatfish",
    "Gurnard": "demersal",
    "Haddock": "demersal",
    "Hake": "demersal",
    "Halibut": "flatfish",
    "John Dory": "other",
    "Lemon Sole": "flatfish",
    "Ling": "demersal",
    "Lobster": "shellfish",
    "Mackerel": "pelagic",
    "Megrim": "flatfish",
    "Monkfish": "other",
    "Octopus": "other",
    "Plaice": "flatfish",
    "Pollack": "demersal",
    "Prawns": "shellfish",
    "Red Mullet": "other",
    "Sand Sole": "flatfish",
    "Scad": "pelagic",
    "Skate": "flatfish",
    "Smoothhound": "other",
    "Spurdog": "other",
    "Squid": "other",
    "Turbot": "flatfish",
    "Weaver": "other",
    "Whiting": "demersal",
    "Witch": "flatfish",
}

CATEGORY_LABELS: dict[str, str] = {
    "all": "All",
    "demersal": "Demersal",
    "flatfish": "Flatfish",
    "shellfish": "Shellfish",
    "pelagic": "Pelagic",
    "other": "Other",
}


def get_species_category(canonical: str) -> str:
    """Return the fishing category for a canonical species name.

    Categories: 'demersal', 'flatfish', 'shellfish', 'pelagic', 'other'
    Unmapped species default to 'other'.
    """
    return _CATEGORY_MAP.get(canonical, "other")
