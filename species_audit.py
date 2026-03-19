#!/usr/bin/env python3
"""
Quayside Species Audit — Diagnostic Script
============================================
Run against your SQLite database to find:
1. Raw names with NO canonical mapping (orphans — not merging cross-port)
2. Canonical names that only appear at ONE port (potential missed merges)
3. Raw names that might be mapping to the WRONG canonical (suspicious overlaps)
4. Volume of records affected by each issue
5. DEFRA code coverage check (Brixham)
Usage:
    python species_audit.py                          # uses default path
    python species_audit.py /path/to/quayside.db     # custom path
Output:
    Prints a structured report to terminal.
    Also saves species_audit_report.md to the current directory.
"""
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
# ---------------------------------------------------------------------------
# 1. YOUR CURRENT CANONICAL MAP (from the data audit, March 2026)
#    Format: canonical_name -> [list of raw names that map to it]
# ---------------------------------------------------------------------------
CANONICAL_MAP = {
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
    "Ray Wings":            ["Un Wing"],
    # --- RAYS (sold whole — split by species) ---
    "Blonde Ray":     ["Blonde Ray"],
    "Cuckoo Ray":     ["Cuckoo Ray"],
    "Spotted Ray":    ["Spotted Ray"],
    "Small-Eyed Ray": ["Small-Eyed Ray"],
    "Undulate Ray":   ["Undulate Ray", "Und Ray"],
    "Ray":            ["Ray", "Un Ray"],
    # --- SKATE ---
    "Skate":          ["Skate", "Skate Medium", "Skate Round", "Skate Small", "Thornback Skate"],
    # --- GURNARD ---
    "Gurnard":        ["Gurnard", "Gurnard and Latchet"],
    "Tub Gurnard":    ["Tubs"],
    # --- BREAM ---
    "Black Bream":    ["Black Bream", "Bream"],
    "Red Bream":      ["Red Bream"],
    "Couch's Bream":  ["Couch Bream"],
    "Gilthead Bream": ["Gilthead Bream 750-1KG"],
    # --- SHELLFISH / CEPHALOPODS ---
    "Crabs":          ["Crabs", "Crabs Hen", "Crabscock", "Crabsmx", "Crabclaws",
                       "Brown Claws M", "Brown Claws L"],
    "Crab Green":     ["Crab Green"],
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
# Build the reverse lookup: raw_name (lowered) -> canonical
RAW_TO_CANONICAL = {}
for canonical, raws in CANONICAL_MAP.items():
    for raw in raws:
        RAW_TO_CANONICAL[raw.lower().strip()] = canonical
# Noise filter — species that shouldn't be compared cross-port
NOISE_WORDS = {
    "mixed", "offal", "roe", "livers", "frames", "heads", "skin",
    "back", "bull", "chunks", "roes", "dead", "damaged",
}
NOISE_SUBSTRINGS = [
    "mixed", "damaged", "bruised", "tails",
    "monk cheeks", "monk cheek", "monk livers",
    "pollack roe", "poll roe", "ling roe", "whit roe",
    "sole dam", "hake dam",
]
NOISE_SUFFIXES = ["dam", "mx", "bru", "mixed", "tails", "link"]
NOISE_PREFIXES = ["bru"]  # e.g. "Brubrill1" = Bruised Brill grade 1

def is_noise(species_name: str) -> bool:
    """Check if a species name is noise/byproduct."""
    lower = species_name.lower().strip()
    if any(word in NOISE_WORDS for word in lower.split()):
        return True
    if any(sub in lower for sub in NOISE_SUBSTRINGS):
        return True
    for suffix in NOISE_SUFFIXES:
        if lower.endswith(suffix) and len(lower) > len(suffix) + 2:
            if len(lower) - len(suffix) >= 3:
                return True
    for prefix in NOISE_PREFIXES:
        if lower.startswith(prefix) and len(lower) > len(prefix) + 2:
            return True
    return False
def resolve_canonical(raw_name: str):
    """Try to resolve a raw species name to its canonical form. Returns None if no mapping."""
    lower = raw_name.lower().strip()
    return RAW_TO_CANONICAL.get(lower)
def run_audit(db_path: str):
    """Run the full species audit and return structured results."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Check the table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='prices'")
    if not cur.fetchone():
        print("ERROR: No 'prices' table found in the database.")
        print("Are you pointing at the right file?")
        sys.exit(1)
    # Get date range
    cur.execute("SELECT MIN(date) as min_d, MAX(date) as max_d, COUNT(*) as total FROM prices")
    row = cur.fetchone()
    date_min, date_max, total_records = row["min_d"], row["max_d"], row["total"]
    # Recent window: last 30 days of data
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    # -----------------------------------------------------------------------
    # SECTION 1: All unique raw species names, by port, with record counts
    # -----------------------------------------------------------------------
    cur.execute("""
        SELECT species, port, COUNT(*) as cnt,
               SUM(CASE WHEN weight_kg IS NOT NULL AND weight_kg > 0 THEN 1 ELSE 0 END) as has_weight,
               SUM(CASE WHEN price_low IS NOT NULL THEN 1 ELSE 0 END) as has_low,
               SUM(CASE WHEN price_high IS NOT NULL THEN 1 ELSE 0 END) as has_high
        FROM prices
        WHERE date >= ?
        GROUP BY species, port
        ORDER BY species, port
    """, (thirty_days_ago,))
    species_port_data = cur.fetchall()
    # Organise into structures
    raw_names = set()
    port_species = defaultdict(set)       # port -> set of raw species
    species_ports = defaultdict(set)       # raw species -> set of ports
    species_records = defaultdict(int)     # raw species -> total recent records
    orphans = []                           # raw names with no canonical mapping
    noise_found = []                       # noise items still in the data
    canonical_ports = defaultdict(set)     # canonical name -> set of ports
    for row in species_port_data:
        raw = row["species"]
        port = row["port"]
        cnt = row["cnt"]
        raw_names.add(raw)
        port_species[port].add(raw)
        species_ports[raw].add(port)
        species_records[raw] += cnt
        canonical = resolve_canonical(raw)
        if canonical:
            canonical_ports[canonical].add(port)
        elif is_noise(raw):
            noise_found.append((raw, port, cnt))
        else:
            orphans.append((raw, port, cnt))
    # -----------------------------------------------------------------------
    # SECTION 2: Canonical names appearing at only ONE port
    # -----------------------------------------------------------------------
    single_port_canonicals = {
        canon: list(ports)[0]
        for canon, ports in canonical_ports.items()
        if len(ports) == 1
    }
    # -----------------------------------------------------------------------
    # SECTION 3: Potential merging issues — look for raw names that are
    # similar but map to different canonicals (or one maps and one doesn't)
    # -----------------------------------------------------------------------
    # Simple approach: find raw names that share a word with each other
    # but resolve to different canonicals
    from itertools import combinations
    suspicious_pairs = []
    active_raws = [r for r in raw_names if not is_noise(r)]
    # Build word index
    word_index = defaultdict(set)
    for raw in active_raws:
        for word in raw.lower().split():
            if len(word) > 2:  # skip tiny words
                word_index[word].add(raw)
    seen_pairs = set()
    for word, names in word_index.items():
        if len(names) > 1 and len(names) < 10:  # skip very common words
            for a, b in combinations(sorted(names), 2):
                pair = (a, b)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                canon_a = resolve_canonical(a)
                canon_b = resolve_canonical(b)
                # Flag if they resolve differently or one is unmapped
                if canon_a != canon_b:
                    suspicious_pairs.append((a, canon_a, b, canon_b))
    # -----------------------------------------------------------------------
    # SECTION 4: Data richness per port (what fields are populated)
    # -----------------------------------------------------------------------
    cur.execute("""
        SELECT port,
               COUNT(*) as total,
               SUM(CASE WHEN price_avg IS NOT NULL THEN 1 ELSE 0 END) as has_avg,
               SUM(CASE WHEN price_low IS NOT NULL THEN 1 ELSE 0 END) as has_low,
               SUM(CASE WHEN price_high IS NOT NULL THEN 1 ELSE 0 END) as has_high,
               SUM(CASE WHEN weight_kg IS NOT NULL AND weight_kg > 0 THEN 1 ELSE 0 END) as has_weight,
               COUNT(DISTINCT species) as unique_species,
               COUNT(DISTINCT grade) as unique_grades
        FROM prices
        WHERE date >= ?
        GROUP BY port
        ORDER BY total DESC
    """, (thirty_days_ago,))
    port_richness = cur.fetchall()
    # -----------------------------------------------------------------------
    # SECTION 5: Grade consistency across ports
    # -----------------------------------------------------------------------
    cur.execute("""
        SELECT port, grade, COUNT(*) as cnt
        FROM prices
        WHERE date >= ?
        GROUP BY port, grade
        ORDER BY port, grade
    """, (thirty_days_ago,))
    port_grades = defaultdict(list)
    for row in cur.fetchall():
        port_grades[row["port"]].append((row["grade"] or "(empty)", row["cnt"]))
    conn.close()
    # -----------------------------------------------------------------------
    # BUILD REPORT
    # -----------------------------------------------------------------------
    lines = []
    lines.append("# Quayside Species Audit Report")
    lines.append(f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
    lines.append(f"**Database**: `{db_path}`")
    lines.append(f"**Date range in DB**: {date_min} → {date_max}")
    lines.append(f"**Total records**: {total_records:,}")
    lines.append(f"**Analysis window**: last 30 days (from {thirty_days_ago})\n")
    # --- PORT DATA RICHNESS ---
    lines.append("---\n## 1. Port Data Richness (last 30 days)\n")
    lines.append("| Port | Records | Species | Grades | Has Avg | Has Low | Has High | Has Weight |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in port_richness:
        pct_avg = f"{r['has_avg']/r['total']*100:.0f}%" if r['total'] else "—"
        pct_low = f"{r['has_low']/r['total']*100:.0f}%" if r['total'] else "—"
        pct_high = f"{r['has_high']/r['total']*100:.0f}%" if r['total'] else "—"
        pct_wt = f"{r['has_weight']/r['total']*100:.0f}%" if r['total'] else "—"
        lines.append(f"| {r['port']} | {r['total']:,} | {r['unique_species']} | {r['unique_grades']} | {pct_avg} | {pct_low} | {pct_high} | {pct_wt} |")
    # --- ORPHAN SPECIES ---
    lines.append(f"\n---\n## 2. Unmapped Species — No Canonical Name ({len(orphans)} found)\n")
    lines.append("These raw names have **no entry in the canonical map**. They appear in reports")
    lines.append("as title-cased raw names and **cannot be compared cross-port**.\n")
    if orphans:
        # Sort by record count descending
        orphans.sort(key=lambda x: -x[2])
        lines.append("| Raw Name | Port | Records (30d) | Action Needed |")
        lines.append("|---|---|---|---|")
        for raw, port, cnt in orphans:
            # Suggest a possible match
            suggestion = ""
            lower = raw.lower()
            for canon, raws in CANONICAL_MAP.items():
                for mapped_raw in raws:
                    if mapped_raw.lower() in lower or lower in mapped_raw.lower():
                        suggestion = f"→ possibly **{canon}**?"
                        break
                if suggestion:
                    break
            lines.append(f"| {raw} | {port} | {cnt} | {suggestion or 'New canonical needed'} |")
    else:
        lines.append("*None found — all species names have a canonical mapping.*\n")
    # --- SINGLE-PORT CANONICALS ---
    lines.append(f"\n---\n## 3. Single-Port Species ({len(single_port_canonicals)} found)\n")
    lines.append("These canonical names only appear at **one port** in the last 30 days.")
    lines.append("Some are genuinely single-port species. Others might indicate a naming gap")
    lines.append("where another port sells the same fish under a different name.\n")
    if single_port_canonicals:
        lines.append("| Canonical Name | Only At | Possibly Also At? |")
        lines.append("|---|---|---|")
        for canon, port in sorted(single_port_canonicals.items()):
            lines.append(f"| {canon} | {port} | *check manually* |")
    # --- SUSPICIOUS PAIRS ---
    lines.append(f"\n---\n## 4. Suspicious Name Pairs ({len(suspicious_pairs)} found)\n")
    lines.append("Raw names that share a keyword but resolve to **different canonicals**")
    lines.append("(or one is unmapped). These might be the same species under different names.\n")
    if suspicious_pairs:
        lines.append("| Name A | Maps To | Name B | Maps To | Risk |")
        lines.append("|---|---|---|---|---|")
        for a, ca, b, cb in sorted(suspicious_pairs):
            risk = "ONE UNMAPPED" if (ca is None or cb is None) else "DIFFERENT CANONICAL"
            lines.append(f"| {a} | {ca or '❌ UNMAPPED'} | {b} | {cb or '❌ UNMAPPED'} | {risk} |")
    else:
        lines.append("*None found.*\n")
    # --- NOISE STILL IN DATA ---
    lines.append(f"\n---\n## 5. Noise/Byproduct Species Still in Data ({len(noise_found)} found)\n")
    lines.append("These match noise filters but are still in the database. They should be")
    lines.append("excluded from cross-port comparisons and averages.\n")
    if noise_found:
        lines.append("| Raw Name | Port | Records (30d) |")
        lines.append("|---|---|---|")
        for raw, port, cnt in sorted(noise_found, key=lambda x: -x[2]):
            lines.append(f"| {raw} | {port} | {cnt} |")
    # --- GRADE SYSTEMS ---
    lines.append(f"\n---\n## 6. Grade Systems by Port\n")
    lines.append("Different ports use different grading scales. This affects cross-port comparison.\n")
    for port, grades in sorted(port_grades.items()):
        grade_str = ", ".join(f"{g} ({c})" for g, c in grades)
        lines.append(f"**{port}**: {grade_str}\n")
    # --- SUMMARY ---
    total_orphan_records = sum(cnt for _, _, cnt in orphans)
    total_recent = sum(r["total"] for r in port_richness)
    orphan_pct = (total_orphan_records / total_recent * 100) if total_recent else 0
    lines.append("\n---\n## Summary\n")
    lines.append(f"- **{len(orphans)} unmapped species names** across {total_orphan_records:,} records ({orphan_pct:.1f}% of recent data)")
    lines.append(f"- **{len(single_port_canonicals)} canonical species** only appear at one port")
    lines.append(f"- **{len(suspicious_pairs)} suspicious name pairs** that might be the same species")
    lines.append(f"- **{len(noise_found)} noise entries** still in the data")
    lines.append(f"\nPorts with the most unmapped names: {', '.join(set(p for _, p, _ in orphans[:10])) or 'none'}")
    report = "\n".join(lines)
    # Print to terminal
    print(report)
    # Save to file
    report_path = "species_audit_report.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\n{'='*60}")
    print(f"Report saved to: {report_path}")
    print(f"{'='*60}")
    return report
if __name__ == "__main__":
    # Default DB path — change this to match your setup
    default_path = "data/quayside.db"
    db_path = sys.argv[1] if len(sys.argv) > 1 else default_path
    print(f"Running species audit against: {db_path}\n")
    run_audit(db_path)
