"""Species name normalisation for cross-port comparison.

Raw species names differ between ports (e.g. "Monks" at Peterhead, "Monk" at Brixham,
"Monk Or Anglers" at Newlyn). This module maps them to canonical display names.

The mapping is applied at **report time only** — the database stores raw names as
scraped, preserving the source exactly. This module is used by report.py when
building cross-port comparisons.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical name → list of raw names found across ports.
# Keep sections alphabetical within each group. Add new entries as new ports
# are added.
# ---------------------------------------------------------------------------
_CANONICAL_MAP: dict[str, list[str]] = {
    # --- CORE COMMERCIAL WHITEFISH ---
    "Cod":            ["Cod", "COD"],
    "Haddock":        ["Haddock", "Haddock Round", "HADD"],
    "Whiting":        ["Whiting", "Whiting Round", "WHIT"],
    "Coley (Saithe)": ["Coley", "Saithe", "Saithe Coal Fish", "Saithe, Coal Fish", "SAITE"],
    "Pollack":        ["Pollack", "Pollock", "Lythe/Pollack", "Pollack Lythe", "Pollack, Lythe"],
    "Hake":           ["Hake", "MSC Hake", "HKE"],
    "Ling":           ["Ling", "LING"],
    "Tusk":           ["Tusk", "TUSK"],
    "Pouting":        ["Pouting", "Pout", "Pout Whiting Pouting Bib", "Pout Whiting, Pouting, Bib"],

    # --- FLATFISH ---
    "Dover Sole":     ["Sole", "Dover Sole"],
    "Lemon Sole":     ["Lemons", "Lem", "Lemon Sole", "LEMS"],
    "Plaice":         ["Plaice", "PLAI"],
    "Megrim":         ["Megrim"],
    "Dab":            ["Dab", "Dabs"],
    "Witch":          ["Witches", "Witch"],
    "Flounder":       ["Flounder", "Flounder/Fluke"],
    "Sand Sole":      ["Sandsol1", "Sandsol2", "Sand Sole"],
    "Halibut":        ["Halibut", "HALI"],
    "Turbot":         ["Turbot", "TURB"],
    "Brill":          ["Brill"],

    # --- PREMIUM / ROUND FISH ---
    "Monkfish":       ["Monks", "Monk", "Monk Or Anglers", "Monkfish", "MONK"],
    "John Dory":      ["Dory", "John Dory"],
    "Catfish":        ["Catfish Scottish", "Catfish"],

    # --- RAY WINGS (sold as wings — split by species) ---
    "Blonde Ray Wings":     ["Bl Wing", "Wings - Blonde"],
    "Cuckoo Ray Wings":     ["Co Wing", "Wings - Cuckoo"],
    "Small-Eyed Ray Wings": ["Sm Wing", "Wings - Small Eyed"],
    "Spotted Ray Wings":    ["Sp Wing", "Wings - Spotted"],
    "Thornback Ray Wings":  ["Th Wing", "Wings - Thorn"],
    "Shagreen Ray Wings":   ["Sha Wing", "Wings - Shag"],
    "Ray Wings":            ["Un Wing"],  # unidentified wing only

    # --- RAYS (sold whole — split by species) ---
    "Blonde Ray":     ["Blonde Ray"],
    "Cuckoo Ray":     ["Cuckoo Ray"],
    "Spotted Ray":    ["Spotted Ray"],
    "Small-Eyed Ray": ["Small-Eyed Ray"],
    "Undulate Ray":   ["Undulate Ray", "Und Ray"],
    "Ray":            ["Ray", "Un Ray"],  # unidentified ray

    # --- SKATE (distinct from rays in trade) ---
    "Skate":          ["Skate", "Skate Medium", "Skate Round", "Skate Small", "Thornback Skate"],

    # --- GURNARD (tub gurnard is distinct product from generic gurnard) ---
    "Gurnard":        ["Gurnard", "Gurnard and Latchet"],
    "Tub Gurnard":    ["Tubs"],

    # --- BREAM (split by species — different products, different prices) ---
    "Black Bream":    ["Black Bream", "Bream"],
    "Red Bream":      ["Red Bream"],
    "Couch's Bream":  ["Couch Bream"],
    "Gilthead Bream": ["Gilthead Bream 750-1KG"],  # Newlyn size-specific entry

    # --- SHELLFISH / CEPHALOPODS ---
    "Crabs":          ["Crabs", "Crabs Hen", "Crabscock", "Crabsmx", "Crabclaws",
                       "Brown Claws M", "Brown Claws L"],
    "Crab Green":     ["Crab Green"],  # green/shore crab — distinct from brown crab
    "Spider Crab":    ["Spider Claws L"],
    "Lobster":        ["Lobster", "Lobsters", "Lobster De", "Lob Nel"],
    "Prawns":         ["Prawns"],
    "Squid":          ["Squid"],
    "Octopus":        ["Octopus", "Mediterranean Octopus Pot Caught", "Oct-Small"],
    "Cuttlefish":     ["Cuttlefish", "Cuttle"],
    "Scallops":       ["Scallop", "Scallop2", "Scallops", "Scall Meat"],
    "Whelks":         ["Whelks"],

    # --- OTHER SPECIES ---
    "Conger Eel":              ["Conger", "Conger Eels"],
    "Eels":                    ["Eels"],
    "Dogfish":                 ["Dogfish"],
    "Lesser Spotted Dogfish":  ["Lesser Spotted Dogfish"],
    "Smoothhound":             ["Smhound", "Smoothhound"],
    "Tope":                    ["Tope"],
    "Spurdog":                 ["Spurdog"],
    "Grey Mullet":             ["Grey Mullet", "Mulgry"],
    "Red Mullet":              ["Mulred", "Red Mullet"],
    "Herring":                 ["Herring"],
    "Mackerel":                ["Mackerel"],
    "Pilchard":                ["Pilchard"],
    "Scad":                    ["Scad/Horse", "Scad SCAD", "Scad"],
    "Weaver":                  ["Weaver"],
}

# Build reverse lookup: raw_name (case-insensitive, stripped) → canonical name
_RAW_TO_CANONICAL: dict[str, str] = {}
for _canonical, _raw_names in _CANONICAL_MAP.items():
    for _raw in _raw_names:
        _RAW_TO_CANONICAL[_raw.lower().strip()] = _canonical


# ---------------------------------------------------------------------------
# Noise filter — species names that are byproducts, damage grades, or mixed
# lots. These are excluded from all cross-port comparisons and report averages.
# ---------------------------------------------------------------------------

# Words that mark a record as noise when they appear as a standalone word
_NOISE_WORDS: set[str] = {
    "mixed", "offal", "roe", "livers", "frames", "heads", "skin",
    "back", "bull", "chunks", "roes", "dead", "damaged",
}

# Substrings that mark a record as noise when found anywhere in the name
_NOISE_SUBSTRINGS: tuple[str, ...] = (
    "mixed", "damaged", "bruised", "tails",
    "monk cheeks", "monk cheek", "monk livers",
    "pollack roe", "poll roe", "ling roe", "whit roe",
    "sole dam", "hake dam",
)

# Brixham-style concatenated suffixes for damaged/mixed/bruised product.
# e.g. "Hadddam" = Haddock damaged, "Solemixed" = Sole mixed,
#      "Monkslink" = Monks link (offcuts), "Megrimbru" = Megrim bruised
_NOISE_SUFFIXES: tuple[str, ...] = ("dam", "mx", "bru", "mixed", "tails", "link")

# Brixham-style prefixes — "bru" + species = bruised, e.g. "Brubrill1" = Bruised Brill grade 1
_NOISE_PREFIXES: tuple[str, ...] = ("bru",)


def is_noisy_species(name: str) -> bool:
    """Return True if this species name is too generic/damaged to be meaningful.

    Used by report builders to filter out noise before cross-port comparisons.
    Catches:
    - Standalone noise words (e.g. "Mixed", "Dead")
    - Noise substrings anywhere in the name (e.g. "Megrim Damaged", "Monk Cheeks")
    - Brixham-style concatenated suffixes (e.g. "Hadddam", "Solemixed", "Megrimbru")
    """
    low = name.lower().strip()

    # Check standalone noise words
    if any(word in _NOISE_WORDS for word in low.split()):
        return True

    # Check substrings
    if any(sub in low for sub in _NOISE_SUBSTRINGS):
        return True

    # Check Brixham-style concatenated suffixes (e.g. "Hadddam", "Megrimbru")
    for suffix in _NOISE_SUFFIXES:
        if low.endswith(suffix) and len(low) > len(suffix) + 2:
            # Prefix must be at least 3 chars to rule out real species names
            if len(low) - len(suffix) >= 3:
                return True

    # Check Brixham-style bruised prefix (e.g. "Brubrill1" = Bruised Brill grade 1)
    for prefix in _NOISE_PREFIXES:
        if low.startswith(prefix) and len(low) > len(prefix) + 2:
            return True

    return False


def normalise_species(raw_name: str) -> str | None:
    """Map a raw scraped species name to its canonical display name.

    Returns:
        None            — if the name matches the noise filter
        canonical str   — if a mapping exists in _CANONICAL_MAP
        title-cased str — if no mapping found (so it still appears in reports,
                          just without cross-port merging)
    """
    if is_noisy_species(raw_name):
        return None
    return _RAW_TO_CANONICAL.get(raw_name.lower().strip(), raw_name.strip().title())


def get_all_canonical_names() -> list[str]:
    """Return sorted list of all canonical species names."""
    return sorted(_CANONICAL_MAP.keys())


# Key commercial species shown in the ticker bar and homepage hero.
# Only these species appear in the floating ticker and landing page data.
KEY_SPECIES: list[str] = [
    "Haddock",
    "Cod",
    "Monkfish",
    "Lemon Sole",
    "Plaice",
    "Whiting",
    "Nephrops",
    "Halibut",
    "Turbot",
    "Coley (Saithe)",
]


# ---------------------------------------------------------------------------
# Category groupings for canonical species names.
# Categories: "demersal", "flatfish", "shellfish", "pelagic", "other"
# ---------------------------------------------------------------------------
_CATEGORY_MAP: dict[str, str] = {
    # Demersal
    "Catfish":                 "demersal",
    "Cod":                     "demersal",
    "Coley (Saithe)":          "demersal",
    "Gurnard":                 "demersal",
    "Haddock":                 "demersal",
    "Hake":                    "demersal",
    "Ling":                    "demersal",
    "Pollack":                 "demersal",
    "Pouting":                 "demersal",
    "Tub Gurnard":             "demersal",
    "Tusk":                    "demersal",
    "Whiting":                 "demersal",
    # Flatfish
    "Brill":                   "flatfish",
    "Dab":                     "flatfish",
    "Dover Sole":              "flatfish",
    "Flounder":                "flatfish",
    "Halibut":                 "flatfish",
    "Lemon Sole":              "flatfish",
    "Megrim":                  "flatfish",
    "Plaice":                  "flatfish",
    "Sand Sole":               "flatfish",
    "Skate":                   "flatfish",
    "Turbot":                  "flatfish",
    "Witch":                   "flatfish",
    # Shellfish
    "Crab Green":              "shellfish",
    "Crabs":                   "shellfish",
    "Cuttlefish":              "shellfish",
    "Lobster":                 "shellfish",
    "Octopus":                 "shellfish",
    "Prawns":                  "shellfish",
    "Scallops":                "shellfish",
    "Spider Crab":             "shellfish",
    "Squid":                   "shellfish",
    "Whelks":                  "shellfish",
    # Pelagic
    "Herring":                 "pelagic",
    "Mackerel":                "pelagic",
    "Pilchard":                "pelagic",
    "Scad":                    "pelagic",
    # Other
    "Black Bream":             "other",
    "Blonde Ray":              "other",
    "Blonde Ray Wings":        "other",
    "Conger Eel":              "other",
    "Couch's Bream":           "other",
    "Cuckoo Ray":              "other",
    "Cuckoo Ray Wings":        "other",
    "Dogfish":                 "other",
    "Eels":                    "other",
    "Gilthead Bream":          "other",
    "Grey Mullet":             "other",
    "John Dory":               "other",
    "Lesser Spotted Dogfish":  "other",
    "Monkfish":                "other",
    "Ray":                     "other",
    "Ray Wings":               "other",
    "Red Bream":               "other",
    "Red Mullet":              "other",
    "Shagreen Ray Wings":      "other",
    "Small-Eyed Ray":          "other",
    "Small-Eyed Ray Wings":    "other",
    "Smoothhound":             "other",
    "Spotted Ray":             "other",
    "Spotted Ray Wings":       "other",
    "Spurdog":                 "other",
    "Thornback Ray Wings":     "other",
    "Tope":                    "other",
    "Undulate Ray":            "other",
    "Weaver":                  "other",
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
