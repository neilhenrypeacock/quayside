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
    "Brill": ["Brill", "Brubrill4"],
    "Catfish": ["Catfish Scottish", "Catfish"],
    "Cod": ["Cod"],
    "Coley (Saithe)": ["Coley", "Saithe", "Saithe, Coal Fish"],
    "Conger Eel": ["Conger", "Conger Eels"],
    "Crabs": ["Crabs", "Crabs Hen", "Crabscock", "Crabsmx", "Crabclaws", "Brown Claws M"],
    "Cuttlefish": ["Cuttlefish", "Cuttle"],
    "Dab": ["Dab", "Dabs"],
    "Dogfish": ["Dogfish"],
    "Dover Sole": ["Sole", "Dover Sole"],
    "Flounder": ["Flounder", "Flounder/Fluke"],
    "Grey Mullet": ["Grey Mullet", "Mulgry"],
    "Gurnard": ["Gurnard", "Gurnard and Latchet"],
    "Haddock": ["Haddock", "Haddock Round"],
    "Hake": ["Hake", "MSC Hake"],
    "Halibut": ["Halibut"],
    "Herring": ["Herring"],
    "John Dory": ["Dory", "John Dory"],
    "Lemon Sole": ["Lemons", "Lem", "Lemon Sole"],
    "Ling": ["Ling"],
    "Lobster": ["Lobster", "Lobsters", "Lobster De", "Lob Nel"],
    "Mackerel": ["Mackerel", "Mac Mx"],
    "Megrim": ["Megrim"],
    "Monkfish": ["Monks", "Monk", "Monk Or Anglers"],
    "Octopus": ["Octopus", "Mediterranean Octopus Pot Caught"],
    "Pilchard": ["Pilchard"],
    "Plaice": ["Plaice", "Plaicemx", "Plc Dam"],
    "Pollack": ["Lythe/Pollack", "Pollack", "Pollack, Lythe"],
    "Pouting": ["Pout Whiting, Pouting, Bib", "Pouting", "Pout"],
    "Prawns": ["Prawns"],
    "Red Bream": ["Red Bream"],
    "Red Mullet": ["Mulred", "Red Mullet"],
    "Sand Sole": ["Sandsol1", "Sandsol2", "Sand Sole"],
    "Scad": ["Scad/Horse", "Scad SCAD", "Scad"],
    "Scallops": ["Scallop", "Scallop2", "Scallops", "Scall Meat"],
    "Skate": ["Skate", "Skate Medium", "Skate Round", "Skate Small"],
    "Smoothhound": ["Smhound", "Smoothhound"],
    "Spider Crab": ["Spider Claws L"],
    "Spurdog": ["Spurdog"],
    "Squid": ["Squid"],
    "Tusk": ["Tusk"],
    "Turbot": ["Turbot"],
    "Rays": ["Blonde Ray", "Cuckoo Ray", "Un Ray", "Und Ray", "Undulate Ray"],
    "Ray Wings": ["Bl Wing", "Sp Wing", "Th Wing", "Un Wing",
                  "Wings - Blonde", "Wings - Cuckoo", "Wings - Small Eyed", "Wings - Spotted"],
    "Weaver": ["Weaver"],
    "Whelks": ["Whelks"],
    "Whiting": ["Whiting", "Whiting Round"],
    "Witch": ["Witches", "Witch"],
    "Eels": ["Eels"],
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
    "Crabs": "shellfish",
    "Cuttlefish": "shellfish",
    "Dab": "flatfish",
    "Dogfish": "other",
    "Dover Sole": "flatfish",
    "Eels": "other",
    "Flounder": "flatfish",
    "Grey Mullet": "other",
    "Gurnard": "demersal",
    "Haddock": "demersal",
    "Hake": "demersal",
    "Halibut": "flatfish",
    "Herring": "pelagic",
    "John Dory": "other",
    "Lemon Sole": "flatfish",
    "Ling": "demersal",
    "Lobster": "shellfish",
    "Mackerel": "pelagic",
    "Megrim": "flatfish",
    "Monkfish": "other",
    "Octopus": "shellfish",
    "Pilchard": "pelagic",
    "Plaice": "flatfish",
    "Pollack": "demersal",
    "Pouting": "demersal",
    "Prawns": "shellfish",
    "Ray Wings": "other",
    "Rays": "other",
    "Red Bream": "other",
    "Red Mullet": "other",
    "Sand Sole": "flatfish",
    "Scad": "pelagic",
    "Scallops": "shellfish",
    "Skate": "flatfish",
    "Smoothhound": "other",
    "Spider Crab": "shellfish",
    "Spurdog": "other",
    "Squid": "shellfish",
    "Tusk": "demersal",
    "Turbot": "flatfish",
    "Weaver": "other",
    "Whelks": "shellfish",
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


# Noisy/generic species names that produce meaningless price comparisons
_NOISE_WORDS = {"mixed", "offal", "roe", "livers", "frames", "heads", "skin",
                 "back", "bull", "chunks", "roes", "poutungutt"}
_NOISE_SUBSTRINGS = ("mixed", "damaged", "bruised", "bru ", " bru", "tails",
                     "dam ", " dam", "monk cheeks", "monk livers", "pollack roe",
                     "ling roe", "sole dam", "hake dam")


def is_noisy_species(name: str) -> bool:
    """Return True if this species name is too generic/damaged to be meaningful.

    Used by report builders to filter out noise before cross-port comparisons.
    """
    low = name.lower().strip()
    if low in _NOISE_WORDS:
        return True
    return any(n in low for n in _NOISE_SUBSTRINGS)
