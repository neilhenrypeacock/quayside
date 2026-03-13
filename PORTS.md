# UK & Ireland Fish Port Data Audit

Daily fish price and landing data sources across every active auction port. Ordered by value and accessibility — prices first.

Last updated: 2026-03-12

---

## 1. Price Data Sources (by value + accessibility)

### Tier A — Public, structured, scrapable today

| # | Port | Region | Format | Price Detail | Species Count | Source | Quayside Status |
|---|------|--------|--------|-------------|---------------|--------|-----------------|
| 1 | **Peterhead** | NE Scotland | XLS | Low / High / Avg per grade | ~20 | SWFPA daily XLS | LIVE |
| 2 | **Scrabster** | N Highlands | HTML table | Bottom / Top per species | 15+ | scrabster.co.uk/port-information/fish-prices/ | NEW — ready to build |
| 3 | **Brixham** | SW England | PDF | Day avg only | 30+ | SWFPA daily PDF (Daily-Fish-Sales-Report) | LIVE |
| 4 | **Kinlochbervie** | NW Highlands | PDF/HTML | Via SWFPA | ~15 | SWFPA event page (needs link discovery) | NEW — investigate |
| 5 | **Lerwick** | Shetland | XLS/PDF | Via SWFPA | ~15 | SWFPA event page (needs link discovery) | NEW — investigate |
| 6 | **Grimsby** | E England | PDF/HTML | Via SWFPA | ~15 | SWFPA event page (needs link discovery) | NEW — investigate |

**SWFPA is the single most important source.** Their daily fish prices page (swfpa.com/downloads/daily-fish-prices/) publishes files covering multiple ports from one event page. Currently we only extract Peterhead XLS and Brixham PDF — there are likely additional port files on the same event pages.

### Tier B — Data exists but blocked or difficult

| # | Port | Region | Blocker | Notes | Contact |
|---|------|--------|---------|-------|---------|
| 7 | **Fraserburgh** | NE Scotland | SWFPA stopped publishing HTML price files (~March 2026) | Scraper exists, will auto-resume if SWFPA resumes | SWFPA |
| 8 | **Lerwick** | Shetland | KOSMOS auction login required for prices | Landings are public, prices behind SSA Web Portal | norma@shetlandauction.com |
| 9 | **Newlyn** | SW England | No structured public data | Blog (Through the Gaps) has anecdotal prices in free text, not scrapable | W Stevenson & Sons (wstevenson.co.uk) |
| 10 | **Grimsby** | E England | Website has zero data despite daily 7am auction | May have SWFPA coverage (see Tier A #6) | grimsbyfishmarket.co.uk |
| 11 | **Brixham** | SW England | Landings behind Aucxis KOSMOS login | Prices already covered via SWFPA PDF; landings need buyer registration | brixhamfishmarket.co.uk |
| 12 | **Macduff** | NE Scotland | Don Fishing may publish PDF (needs URL discovery) | Likely in SWFPA reports | donfishing.com |

### Tier C — Behind a wall, needs partnership to unlock

| # | Port | Region | Country | Auction System | Operator | Contact |
|---|------|--------|---------|----------------|----------|---------|
| 13 | **Kilkeel** | Co. Down | N. Ireland | Electronic (Halster/PEFA) | NI Fishery Harbour Authority | NIFHA |
| 14 | **Ardglass** | Co. Down | N. Ireland | Electronic (PEFA) | NIFHA | NIFHA |
| 15 | **Portavogie** | Co. Down | N. Ireland | Electronic | NIFHA | NIFHA |
| 16 | **Castletownbere** | Co. Cork | Ireland | Yes | Fishermen's Co-Op Society | Direct contact |
| 17 | **Killybegs** | Co. Donegal | Ireland | Yes (pelagic focus) | Killybegs Fishermen's Org | KFO |
| 18 | **Howth** | Co. Dublin | Ireland | Yes | Various agents (Beshoffs) | Direct contact |
| 19 | **Dunmore East** | Co. Waterford | Ireland | Yes | DAFM harbour centre | DAFM |
| 20 | **Rossaveal** | Co. Galway | Ireland | Yes | DAFM harbour centre | DAFM |
| 21 | **Dingle** | Co. Kerry | Ireland | Yes | DAFM harbour centre | DAFM |
| 22 | **Lowestoft** | E England | England | Yes (daily 7am) | BFP Eastern Ltd | Direct contact |
| 23 | **Fleetwood** | NW England | England | Yes | Fleetwood fish market | Direct contact |
| 24 | **Whitby** | NE England | England | Yes | Harbour authority | Direct contact |
| 25 | **Milford Haven** | Pembrokeshire | Wales | Landing/processing | Welsh Seafoods | Daily list on request |
| 26 | **Eyemouth** | SE Scotland | Scotland | Yes | Fisherman's Mutual Assoc | Direct contact |
| 27 | **Mallaig** | W Highlands | Scotland | Landing port | Harbour office | Direct contact |
| 28 | **Pittenweem** | Fife | Scotland | Landing port | Local agents | Direct contact |
| 29 | **Scarborough** | NE England | England | Yes | Local market | Direct contact |
| 30 | **Bridlington** | E England | England | Landing port | Local market | Direct contact |

### Closed / No Auction

| Port | Note |
|------|------|
| Aberdeen | Fish market closed 2007. All fish routes through Peterhead. |
| Plymouth | Plymouth Trawler Agents liquidated May 2024. Fish now goes to Brixham/Newlyn. |
| Hull | Processing hub only, not a landing port. |
| Great Yarmouth | General retail market, no fish auction. |
| Whitehaven | Informal ad-hoc sales via Whitehaven Fishermen's Cooperative (Facebook). |
| Lochinver | Annual stats only (Marine Scotland). No daily data. |
| Oban | Landing port, no formal auction with published prices. |

---

## 2. Landing Data Sources

| # | Port | Format | Source | Quayside Status |
|---|------|--------|--------|-----------------|
| 1 | **Peterhead** | HTML table | peterheadport.co.uk/fish-auction/ | LIVE |
| 2 | **Lerwick/Scalloway** | HTML table | shetlandauction.com/ssa-today | LIVE |
| 3 | **Lerwick/Scalloway** | PDF (detailed, with grades) | shetlandauction.com/landings-table-pdf?day=0 | NEW — parameterised URL |
| 4 | **Scrabster** | PDF | donfishing.com (Daily-Market-Report PDF) | NEW — needs PDF parse |
| 5 | **Kinlochbervie** | PDF | donfishing.com (fish-selling/kinlochbervie/) | NEW — needs PDF parse |
| 6 | **Macduff** | PDF | donfishing.com | NEW — needs URL discovery |
| 7 | **Fraserburgh** | JS-rendered HTML | fraserburgh-harbour.co.uk/fish-landings/market/ | BLOCKED — needs headless browser + possible reCAPTCHA |
| 8 | **Brixham** | Boats Due (schedule only) | brixhamfishmarket.co.uk/boats-due/ | Low value — no quantities |

---

## 3. Geographic Coverage

### Where we have data (or can get it easily)

```
                    SHETLAND
                    Lerwick ● (landings LIVE, prices via SWFPA?)
                    Scalloway ●

              NORTHERN HIGHLANDS
              Scrabster ● (prices NEW, landings NEW)
              Kinlochbervie ● (prices via SWFPA?, landings NEW)
              Lochinver ○ (no data)

        NE SCOTLAND (the hub — 60%+ of UK whitefish)
        Peterhead ● (LIVE — prices + landings)
        Fraserburgh ◐ (prices dormant, landings blocked)
        Macduff ◐ (needs investigation)

    SE SCOTLAND                    N. IRELAND
    Eyemouth ○                     Kilkeel ○
    Pittenweem ○                   Ardglass ○
                                   Portavogie ○

    NW ENGLAND         NE ENGLAND          E ENGLAND
    Fleetwood ○        Whitby ○            Grimsby ◐ (SWFPA?)
                       Scarborough ○       Lowestoft ○

    WALES                          SW ENGLAND
    Milford Haven ○                Brixham ● (prices LIVE)
                                   Newlyn ○ (no structured data)
                                   Plymouth ✕ (closed 2024)

    IRELAND
    Killybegs ○  Howth ○  Dunmore East ○
    Castletownbere ○  Dingle ○  Rossaveal ○

● = data live or easy to add    ◐ = partial / difficult    ○ = no public data    ✕ = closed
```

### Regional gaps

| Region | Ports | Status | Value of unlocking |
|--------|-------|--------|-------------------|
| **N. Ireland** | 3 ports with electronic auctions | All behind login (Halster/PEFA) | High — only region with electronic auction data, good for instant prices |
| **Ireland** | 6+ major harbour centres | Zero public daily data | Very high — entire country is a blank spot |
| **SW England** | Newlyn (2nd biggest English port) | No structured data | High — Newlyn + Brixham would cover the whole SW |
| **E England** | Grimsby, Lowestoft | Grimsby may have SWFPA data | Medium — Grimsby is UK's historic fish capital |
| **NE England** | Whitby, Scarborough | No public data | Low — smaller volumes |
| **Wales** | Milford Haven | Daily list available on request | Medium — shows willing |

---

## 4. Species Crossover Analysis

This is the core value proposition: comparing the same species across ports.

### Core Whitefish — available at most ports

| Species | Peterhead | Scrabster | Lerwick | Brixham | Grimsby | Newlyn | NI | Ireland |
|---------|-----------|-----------|---------|---------|---------|-------|-----|---------|
| **Cod** | Graded (A1-A5) | Low/High | Graded (1-4) | Day avg | Via SWFPA? | Unknown | Unknown | Unknown |
| **Haddock** | Graded + Round | Low/High | Graded (1-6+Rnd) | Day avg | Via SWFPA? | Unknown | Unknown | Unknown |
| **Whiting** | Graded + Round | Low/High | Graded (2-4+Rnd) | Day avg | Via SWFPA? | Unknown | Unknown | Unknown |

These three species are the bread and butter of cross-port comparison. A buyer in Glasgow could compare Peterhead Cod A2 vs Scrabster Cod vs Lerwick Cod Grade 2 every morning.

### High-Value Species — strong price comparison potential

| Species | Peterhead | Scrabster | Lerwick | Brixham |
|---------|-----------|-----------|---------|---------|
| **Monks/Monkfish** | Yes | Yes | Yes | Yes (as "Monk") |
| **Hake** | Yes | Yes | Yes | Yes |
| **Turbot** | Yes (single price) | No | Yes | Yes |
| **Lemon Sole** | Yes (as "Lemons") | Yes | Yes | Yes |
| **Megrim** | Yes | No | Yes | Yes |

Premium species command the highest prices and have the most volatile day-to-day swings. Cross-port comparison here is where buyers get the most value.

### Regional Species — limited to certain areas

| Species | Where | Notes |
|---------|-------|-------|
| **Saithe** | Peterhead, Lerwick, Scrabster | Primarily Scottish/Shetland |
| **Squid** | Peterhead, Scrabster, Lerwick | Seasonal |
| **John Dory** | Scrabster, Brixham | SW England + N Scotland |
| **Brill** | Scrabster, Brixham | Channel / North Sea |
| **Pollock** | Scrabster | More common in SW but appears in North |
| **Thornback Skate** | Scrabster | Regional |
| **Catfish** | Peterhead (as "Catfish Scottish"), Lerwick | Scottish |
| **Prawns/Langoustine** | Lerwick, Mallaig | High value, mainly west coast + Shetland |

### Pelagic Species — different market entirely

| Species | Key Port | Notes |
|---------|----------|-------|
| **Mackerel** | Killybegs, Fraserburgh, Lerwick | Seasonal (Oct-Mar), massive volumes |
| **Herring** | Killybegs, Fraserburgh | Seasonal |
| **Blue Whiting** | Killybegs | Industrial, very high volume |

Pelagic fish trades differently (bulk contracts, not daily auction). Less relevant for daily price comparison but important for volume tracking.

### Species Name Normalisation Challenge

The same fish has different names across ports:

| Canonical | Peterhead XLS | Scrabster HTML | Lerwick HTML | Brixham PDF |
|-----------|--------------|----------------|--------------|-------------|
| Monkfish | Monks | Monkfish | Monks | Monk |
| Lemon Sole | Lemons | Lemon Sole | Lemon Sole | Lemon Sole |
| Skate | — | Thornback Skate | Skate | Skate |
| Catfish | Catfish Scottish | — | Catfish | — |

A normalisation mapping will be needed to enable cross-port comparison.

---

## 5. Aggregated & Government Sources

These are not daily price feeds but provide context and validation.

| Source | URL | Coverage | Frequency | Format | Use |
|--------|-----|----------|-----------|--------|-----|
| **SWFPA** | swfpa.com/downloads/daily-fish-prices/ | Scottish + English ports | Daily | XLS, PDF, HTML | PRIMARY — multi-port daily prices |
| **EUMOFA** | eumofa.eu/bulk-download | EU + UK + Ireland | Weekly (CSV) | CSV bulk download | Cross-reference, weekly aggregates |
| **MMO** | gov.uk/government/.../monthly-uk-sea-fisheries-statistics | All UK ports | Monthly | ODS/Excel | Validation, port ranking by volume |
| **Marine Scotland** | data.marine.gov.scot | Scottish ports | Annual | CSV | Reference, spatial data |
| **SFPA Ireland** | sfpa.ie/Statistics | All Irish ports | Annual | PDF | Irish reference |
| **BIM Ireland** | bim.ie/publications/fisheries/ | Irish industry | Annual | PDF | Industry context |
| **CSO Ireland** | data.gov.ie (ATA06 dataset) | Irish avg prices | Unknown | CSV/API | Investigate granularity |
| **Seafish UK** | seafish.org/insight-and-research/ | UK-wide | Monthly | Tableau, PDF | Market context |
| **Don Fishing** | donfishing.com/fish-selling/ | Scrabster, Kinlochbervie, Peterhead, Macduff | Daily | PDF | Landings (boxes by species/vessel) |

---

## 6. Electronic Auction Platforms

Two platforms dominate UK fish auctions. Partnership with either would unlock multiple ports at once.

### Aucxis KOSMOS
- **Used at:** Peterhead (transitioning from shout), Lerwick/Scalloway, Brixham
- **Data:** Real-time auction clock, pre-landing supply, transaction history
- **Access:** Commercial buyer registration only
- **HQ:** Belgium
- **Value:** Partnership would unlock price data from 3+ ports simultaneously

### PEFA (Pan European Fish Auctions)
- **Used at:** Ardglass (N. Ireland), possibly other NI ports, plus Belgium/Netherlands/Wales
- **Data:** Electronic Dutch clock auction data, historical prices
- **Access:** PEFA contract + buyer number + bank guarantee
- **Value:** Would unlock Northern Ireland ports

---

## 7. Partner Strategy

### The pitch

"We already aggregate daily fish prices from X UK ports automatically. Here's the full landscape of what's possible — and what a media partner's reach could unlock."

### What a media partner (Fish Daily etc.) could unlock

| Target | Ports | Method | Why it matters |
|--------|-------|--------|---------------|
| **NIFHA** | Kilkeel, Ardglass, Portavogie | Editorial relationship / feature coverage | Opens all of Northern Ireland (3 ports, electronic auction data) |
| **DAFM Ireland** | Dunmore East, Rossaveal, Dingle + others | Government engagement / industry coverage | Opens entire Republic of Ireland |
| **Aucxis** | Peterhead, Lerwick, Brixham | Technology partnership / data licensing | Unlocks real-time auction data from 3 major ports |
| **W Stevenson** | Newlyn | Direct relationship | Opens England's 2nd-biggest fish port |
| **BFP Eastern** | Lowestoft | Direct relationship | Opens East Anglia |
| **Grimsby Fish Market** | Grimsby | Direct relationship | Opens the historic capital of UK fishing |
| **Irish Co-Ops** | Castletownbere, Killybegs, Howth | Industry body engagement (BIM, KFO) | Opens Ireland's biggest whitefish + pelagic ports |

### Revenue model
- Rev share on subscriber/API access
- Partner provides: audience, industry credibility, door-opening for gated ports
- Quayside provides: technology, data aggregation, daily delivery

### MVP demonstrates
- Automated daily scraping from 5-7 ports
- Cross-port species price comparison
- The full audit (this document) showing the addressable market
- Technical capability to add ports rapidly once data access is granted

---

## 8. Key Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Peterhead E-Auction launch (March 31, 2026) | Breaks landings scraper | Monitor new site, adapt scraper before cutover |
| SWFPA stops publishing more port files | Loses multi-port price coverage | Direct relationships with port authorities |
| Species names diverge further as ports added | Cross-port comparison breaks | Build normalisation mapping early |
| Auction systems add bot detection | Scraping blocked | Rate limiting, proper User-Agent, consider data partnerships |
| Irish ports have no public data infrastructure | Ireland stays blank | Needs media partner leverage or government engagement |
