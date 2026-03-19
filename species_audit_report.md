# Quayside Species Audit Report
*Generated 2026-03-19 09:55*

**Database**: `data/quayside.db`
**Date range in DB**: 2026-02-10 → 2026-03-19
**Total records**: 2,932
**Analysis window**: last 30 days (from 2026-02-17)

---
## 1. Port Data Richness (last 30 days)

| Port | Records | Species | Grades | Has Avg | Has Low | Has High | Has Weight |
|---|---|---|---|---|---|---|---|
| Peterhead | 887 | 20 | 10 | 100% | 95% | 100% | 0% |
| Demo Port | 704 | 16 | 2 | 100% | 100% | 100% | 0% |
| Brixham | 453 | 115 | 11 | 100% | 0% | 0% | 60% |
| Newlyn | 416 | 67 | 15 | 100% | 0% | 0% | 65% |
| Lerwick | 260 | 33 | 7 | 100% | 0% | 100% | 77% |
| Scrabster | 15 | 15 | 1 | 100% | 87% | 100% | 0% |

---
## 2. Unmapped Species — No Canonical Name (5 found)

These raw names have **no entry in the canonical map**. They appear in reports
as title-cased raw names and **cannot be compared cross-port**.

| Raw Name | Port | Records (30d) | Action Needed |
|---|---|---|---|
| Poutungutt | Brixham | 3 | → possibly **Pouting**? |
| Dory Mini | Brixham | 2 | → possibly **John Dory**? |
| Breamgilth | Brixham | 1 | → possibly **Black Bream**? |
| M | Newlyn | 1 | → possibly **Hake**? |
| Megrimmixe | Brixham | 1 | → possibly **Megrim**? |

---
## 3. Single-Port Species (21 found)

These canonical names only appear at **one port** in the last 30 days.
Some are genuinely single-port species. Others might indicate a naming gap
where another port sells the same fish under a different name.

| Canonical Name | Only At | Possibly Also At? |
|---|---|---|
| Blonde Ray | Newlyn | *check manually* |
| Couch's Bream | Newlyn | *check manually* |
| Crab Green | Brixham | *check manually* |
| Cuckoo Ray | Newlyn | *check manually* |
| Dogfish | Lerwick | *check manually* |
| Eels | Lerwick | *check manually* |
| Gilthead Bream | Newlyn | *check manually* |
| Herring | Brixham | *check manually* |
| Lesser Spotted Dogfish | Newlyn | *check manually* |
| Pilchard | Brixham | *check manually* |
| Pouting | Newlyn | *check manually* |
| Prawns | Lerwick | *check manually* |
| Ray | Brixham | *check manually* |
| Ray Wings | Brixham | *check manually* |
| Red Bream | Newlyn | *check manually* |
| Small-Eyed Ray | Newlyn | *check manually* |
| Spider Crab | Newlyn | *check manually* |
| Spotted Ray | Newlyn | *check manually* |
| Tub Gurnard | Brixham | *check manually* |
| Weaver | Newlyn | *check manually* |
| Whelks | Brixham | *check manually* |

---
## 4. Suspicious Name Pairs (93 found)

Raw names that share a keyword but resolve to **different canonicals**
(or one is unmapped). These might be the same species under different names.

| Name A | Maps To | Name B | Maps To | Risk |
|---|---|---|---|---|
| Bl Wing | Blonde Ray Wings | Co Wing | Cuckoo Ray Wings | DIFFERENT CANONICAL |
| Bl Wing | Blonde Ray Wings | Sha Wing | Shagreen Ray Wings | DIFFERENT CANONICAL |
| Bl Wing | Blonde Ray Wings | Sm Wing | Small-Eyed Ray Wings | DIFFERENT CANONICAL |
| Bl Wing | Blonde Ray Wings | Sp Wing | Spotted Ray Wings | DIFFERENT CANONICAL |
| Bl Wing | Blonde Ray Wings | Th Wing | Thornback Ray Wings | DIFFERENT CANONICAL |
| Bl Wing | Blonde Ray Wings | Un Wing | Ray Wings | DIFFERENT CANONICAL |
| Black Bream | Black Bream | Couch Bream | Couch's Bream | DIFFERENT CANONICAL |
| Black Bream | Black Bream | Gilthead Bream 750-1KG | Gilthead Bream | DIFFERENT CANONICAL |
| Black Bream | Black Bream | Red Bream | Red Bream | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Cuckoo Ray | Cuckoo Ray | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Ray | Ray | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Small-Eyed Ray | Small-Eyed Ray | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Spotted Ray | Spotted Ray | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Un Ray | Ray | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Und Ray | Undulate Ray | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Undulate Ray | Undulate Ray | DIFFERENT CANONICAL |
| Blonde Ray | Blonde Ray | Wings - Blonde | Blonde Ray Wings | DIFFERENT CANONICAL |
| Bream | Black Bream | Couch Bream | Couch's Bream | DIFFERENT CANONICAL |
| Bream | Black Bream | Gilthead Bream 750-1KG | Gilthead Bream | DIFFERENT CANONICAL |
| Bream | Black Bream | Red Bream | Red Bream | DIFFERENT CANONICAL |
| Brown Claws L | Crabs | Spider Claws L | Spider Crab | DIFFERENT CANONICAL |
| Brown Claws M | Crabs | Spider Claws L | Spider Crab | DIFFERENT CANONICAL |
| Co Wing | Cuckoo Ray Wings | Sha Wing | Shagreen Ray Wings | DIFFERENT CANONICAL |
| Co Wing | Cuckoo Ray Wings | Sm Wing | Small-Eyed Ray Wings | DIFFERENT CANONICAL |
| Co Wing | Cuckoo Ray Wings | Sp Wing | Spotted Ray Wings | DIFFERENT CANONICAL |
| Co Wing | Cuckoo Ray Wings | Th Wing | Thornback Ray Wings | DIFFERENT CANONICAL |
| Co Wing | Cuckoo Ray Wings | Un Wing | Ray Wings | DIFFERENT CANONICAL |
| Conger Eels | Conger Eel | Eels | Eels | DIFFERENT CANONICAL |
| Couch Bream | Couch's Bream | Gilthead Bream 750-1KG | Gilthead Bream | DIFFERENT CANONICAL |
| Couch Bream | Couch's Bream | Red Bream | Red Bream | DIFFERENT CANONICAL |
| Cuckoo Ray | Cuckoo Ray | Ray | Ray | DIFFERENT CANONICAL |
| Cuckoo Ray | Cuckoo Ray | Small-Eyed Ray | Small-Eyed Ray | DIFFERENT CANONICAL |
| Cuckoo Ray | Cuckoo Ray | Spotted Ray | Spotted Ray | DIFFERENT CANONICAL |
| Cuckoo Ray | Cuckoo Ray | Un Ray | Ray | DIFFERENT CANONICAL |
| Cuckoo Ray | Cuckoo Ray | Und Ray | Undulate Ray | DIFFERENT CANONICAL |
| Cuckoo Ray | Cuckoo Ray | Undulate Ray | Undulate Ray | DIFFERENT CANONICAL |
| Cuckoo Ray | Cuckoo Ray | Wings - Cuckoo | Cuckoo Ray Wings | DIFFERENT CANONICAL |
| Dogfish | Dogfish | Lesser Spotted Dogfish | Lesser Spotted Dogfish | DIFFERENT CANONICAL |
| Dory | John Dory | Dory Mini | ❌ UNMAPPED | ONE UNMAPPED |
| Dory Mini | ❌ UNMAPPED | John Dory | John Dory | ONE UNMAPPED |
| Dover Sole | Dover Sole | Lemon Sole | Lemon Sole | DIFFERENT CANONICAL |
| Dover Sole | Dover Sole | Sand Sole | Sand Sole | DIFFERENT CANONICAL |
| Gilthead Bream 750-1KG | Gilthead Bream | Red Bream | Red Bream | DIFFERENT CANONICAL |
| Grey Mullet | Grey Mullet | Red Mullet | Red Mullet | DIFFERENT CANONICAL |
| Haddock Round | Haddock | Skate Round | Skate | DIFFERENT CANONICAL |
| Haddock Round | Haddock | Whiting Round | Whiting | DIFFERENT CANONICAL |
| Lemon Sole | Lemon Sole | Sand Sole | Sand Sole | DIFFERENT CANONICAL |
| Lemon Sole | Lemon Sole | Sole | Dover Sole | DIFFERENT CANONICAL |
| Lesser Spotted Dogfish | Lesser Spotted Dogfish | Spotted Ray | Spotted Ray | DIFFERENT CANONICAL |
| Lesser Spotted Dogfish | Lesser Spotted Dogfish | Wings - Spotted | Spotted Ray Wings | DIFFERENT CANONICAL |
| Ray | Ray | Small-Eyed Ray | Small-Eyed Ray | DIFFERENT CANONICAL |
| Ray | Ray | Spotted Ray | Spotted Ray | DIFFERENT CANONICAL |
| Ray | Ray | Und Ray | Undulate Ray | DIFFERENT CANONICAL |
| Ray | Ray | Undulate Ray | Undulate Ray | DIFFERENT CANONICAL |
| Red Bream | Red Bream | Red Mullet | Red Mullet | DIFFERENT CANONICAL |
| Sand Sole | Sand Sole | Sole | Dover Sole | DIFFERENT CANONICAL |
| Sha Wing | Shagreen Ray Wings | Sm Wing | Small-Eyed Ray Wings | DIFFERENT CANONICAL |
| Sha Wing | Shagreen Ray Wings | Sp Wing | Spotted Ray Wings | DIFFERENT CANONICAL |
| Sha Wing | Shagreen Ray Wings | Th Wing | Thornback Ray Wings | DIFFERENT CANONICAL |
| Sha Wing | Shagreen Ray Wings | Un Wing | Ray Wings | DIFFERENT CANONICAL |
| Skate Round | Skate | Whiting Round | Whiting | DIFFERENT CANONICAL |
| Skate Small | Skate | Wings - Small Eyed | Small-Eyed Ray Wings | DIFFERENT CANONICAL |
| Sm Wing | Small-Eyed Ray Wings | Sp Wing | Spotted Ray Wings | DIFFERENT CANONICAL |
| Sm Wing | Small-Eyed Ray Wings | Th Wing | Thornback Ray Wings | DIFFERENT CANONICAL |
| Sm Wing | Small-Eyed Ray Wings | Un Wing | Ray Wings | DIFFERENT CANONICAL |
| Small-Eyed Ray | Small-Eyed Ray | Spotted Ray | Spotted Ray | DIFFERENT CANONICAL |
| Small-Eyed Ray | Small-Eyed Ray | Un Ray | Ray | DIFFERENT CANONICAL |
| Small-Eyed Ray | Small-Eyed Ray | Und Ray | Undulate Ray | DIFFERENT CANONICAL |
| Small-Eyed Ray | Small-Eyed Ray | Undulate Ray | Undulate Ray | DIFFERENT CANONICAL |
| Sp Wing | Spotted Ray Wings | Th Wing | Thornback Ray Wings | DIFFERENT CANONICAL |
| Sp Wing | Spotted Ray Wings | Un Wing | Ray Wings | DIFFERENT CANONICAL |
| Spotted Ray | Spotted Ray | Un Ray | Ray | DIFFERENT CANONICAL |
| Spotted Ray | Spotted Ray | Und Ray | Undulate Ray | DIFFERENT CANONICAL |
| Spotted Ray | Spotted Ray | Undulate Ray | Undulate Ray | DIFFERENT CANONICAL |
| Spotted Ray | Spotted Ray | Wings - Spotted | Spotted Ray Wings | DIFFERENT CANONICAL |
| Th Wing | Thornback Ray Wings | Un Wing | Ray Wings | DIFFERENT CANONICAL |
| Un Ray | Ray | Und Ray | Undulate Ray | DIFFERENT CANONICAL |
| Un Ray | Ray | Undulate Ray | Undulate Ray | DIFFERENT CANONICAL |
| Wings - Blonde | Blonde Ray Wings | Wings - Cuckoo | Cuckoo Ray Wings | DIFFERENT CANONICAL |
| Wings - Blonde | Blonde Ray Wings | Wings - Shag | Shagreen Ray Wings | DIFFERENT CANONICAL |
| Wings - Blonde | Blonde Ray Wings | Wings - Small Eyed | Small-Eyed Ray Wings | DIFFERENT CANONICAL |
| Wings - Blonde | Blonde Ray Wings | Wings - Spotted | Spotted Ray Wings | DIFFERENT CANONICAL |
| Wings - Blonde | Blonde Ray Wings | Wings - Thorn | Thornback Ray Wings | DIFFERENT CANONICAL |
| Wings - Cuckoo | Cuckoo Ray Wings | Wings - Shag | Shagreen Ray Wings | DIFFERENT CANONICAL |
| Wings - Cuckoo | Cuckoo Ray Wings | Wings - Small Eyed | Small-Eyed Ray Wings | DIFFERENT CANONICAL |
| Wings - Cuckoo | Cuckoo Ray Wings | Wings - Spotted | Spotted Ray Wings | DIFFERENT CANONICAL |
| Wings - Cuckoo | Cuckoo Ray Wings | Wings - Thorn | Thornback Ray Wings | DIFFERENT CANONICAL |
| Wings - Shag | Shagreen Ray Wings | Wings - Small Eyed | Small-Eyed Ray Wings | DIFFERENT CANONICAL |
| Wings - Shag | Shagreen Ray Wings | Wings - Spotted | Spotted Ray Wings | DIFFERENT CANONICAL |
| Wings - Shag | Shagreen Ray Wings | Wings - Thorn | Thornback Ray Wings | DIFFERENT CANONICAL |
| Wings - Small Eyed | Small-Eyed Ray Wings | Wings - Spotted | Spotted Ray Wings | DIFFERENT CANONICAL |
| Wings - Small Eyed | Small-Eyed Ray Wings | Wings - Thorn | Thornback Ray Wings | DIFFERENT CANONICAL |
| Wings - Spotted | Spotted Ray Wings | Wings - Thorn | Thornback Ray Wings | DIFFERENT CANONICAL |

---
## 5. Noise/Byproduct Species Still in Data (65 found)

These match noise filters but are still in the database. They should be
excluded from cross-port comparisons and averages.

| Raw Name | Port | Records (30d) |
|---|---|---|
| Tur Bru | Brixham | 13 |
| Megrim Damaged | Newlyn | 11 |
| Megrim Bruised | Lerwick | 7 |
| Back | Brixham | 3 |
| Brubrill4 | Brixham | 3 |
| Bull | Brixham | 3 |
| Chunks | Newlyn | 3 |
| Damaged | Newlyn | 3 |
| Hake Dam | Brixham | 3 |
| Haketails | Brixham | 3 |
| Lemmixed | Brixham | 3 |
| Sole Dam | Brixham | 3 |
| Bream Dam | Brixham | 2 |
| Breammx | Brixham | 2 |
| Brill Dam | Brixham | 2 |
| Brubrill2 | Brixham | 2 |
| Brubrill3 | Brixham | 2 |
| Brubrill5 | Brixham | 2 |
| Dead | Brixham | 2 |
| Dogmx | Brixham | 2 |
| Gurnardmx | Brixham | 2 |
| Hadddam | Brixham | 2 |
| Ling Roe | Brixham | 2 |
| Ling Roe | Newlyn | 2 |
| Lingdam | Brixham | 2 |
| Mac Mx | Brixham | 2 |
| Macdam | Brixham | 2 |
| Megrimbru | Brixham | 2 |
| Mixed | Lerwick | 2 |
| Monk Cheek | Brixham | 2 |
| Monk Cheeks | Newlyn | 2 |
| Monkslink | Brixham | 2 |
| Mulreddam | Brixham | 2 |
| Plc Dam | Brixham | 2 |
| Poll Dam | Brixham | 2 |
| Polltails | Brixham | 2 |
| Poutmixed | Brixham | 2 |
| Poutmx | Brixham | 2 |
| Solemixed | Brixham | 2 |
| Squid Mx | Brixham | 2 |
| Tur Dam | Brixham | 2 |
| Whitdam | Brixham | 2 |
| Whitingmx | Brixham | 2 |
| Whittails | Brixham | 2 |
| Brubrill1 | Brixham | 1 |
| Coleydam | Brixham | 1 |
| Dabmx | Brixham | 1 |
| Dorymx | Brixham | 1 |
| Haddock Mx | Brixham | 1 |
| Haddtails | Brixham | 1 |
| Macmixed | Brixham | 1 |
| Meg Bru | Brixham | 1 |
| Mixed Whitefish | Newlyn | 1 |
| Monk Dam | Brixham | 1 |
| Monk Livers | Newlyn | 1 |
| Monk Mx | Brixham | 1 |
| Monkmixed | Brixham | 1 |
| Mulredmx | Brixham | 1 |
| Plaicemx | Brixham | 1 |
| Poll Roe | Brixham | 1 |
| Pollack Roe | Newlyn | 1 |
| Roes | Lerwick | 1 |
| Turbot Dam | Brixham | 1 |
| Whit Roe | Brixham | 1 |
| Whiting Mx | Brixham | 1 |

---
## 6. Grade Systems by Port

Different ports use different grading scales. This affects cross-port comparison.

**Brixham**: 1 (60), 10 (3), 2 (76), 3 (61), 4 (50), 5 (22), 6 (12), 7 (10), 8 (5), 9 (4), ALL (150)

**Demo Port**: A1 (352), A2 (352)

**Lerwick**: 0 (6), 1 (23), 2 (41), 3 (56), 4 (89), 5 (32), 6 (13)

**Newlyn**: 0-2kg (2), 1 (64), 10 (3), 2 (67), 3 (77), 4 (76), 5 (43), 6 (24), 7 (11), 8 (9), 9 (3), ALL (31), LM (2), M (2), S (2)

**Peterhead**: A1 (136), A2 (186), A3 (189), A4 (159), A4 - Round (21), A4-Chipper (22), A4-Metro (21), A5 (53), ALL (99), B4 (1)

**Scrabster**: ALL (15)


---
## Summary

- **5 unmapped species names** across 8 records (0.3% of recent data)
- **21 canonical species** only appear at one port
- **93 suspicious name pairs** that might be the same species
- **65 noise entries** still in the data

Ports with the most unmapped names: Brixham, Newlyn