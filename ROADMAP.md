# Quayside — Roadmap

UK fish auction data pipeline. Scrapes landings + prices, stores in SQLite, delivers daily reports.

**Repo**: github.com/neilhenrypeacock/quayside (private)

---

## Phase 1 — Peterhead Pipeline ✅ DONE

**Goal**: Scrape Peterhead landings + prices daily, store & export CSVs.

- [x] Landings scraper (peterheadport.co.uk HTML table)
- [x] Price scraper (SWFPA daily XLS via calendar discovery)
- [x] SQLite storage with upsert (no duplicates)
- [x] CSV export (landings + prices)
- [x] launchd scheduled at 10:15 AM weekdays
- [x] Tests with saved fixtures (9 passing)

**Known risk**: Peterhead launching new E-Auction system March 31, 2026. Scraper may need updating.

---

## Phase 2 — More Ports (IN PROGRESS)

**Goal**: Expand to all UK ports with public price/landing data.

### Brixham (Devon) ✅ DONE
- [x] Prices: SWFPA daily PDF parsed with pdfplumber. Day average only (no low/high split).
- [ ] Landings: Not publicly available. BrixhamFish Ltd private operator.

### Lerwick (Shetland) — PARTIAL
- [x] Landings: `shetlandauction.com/ssa-today` — clean HTML table
- [ ] Prices: **BLOCKED** — requires Kosmos auction login. Contact norma@shetlandauction.com.

### Newlyn (Cornwall) ✅ DONE
- [x] Prices: SWFPA daily PDF parsed with pdfplumber. Same format as Brixham.
- [ ] Landings: Not publicly available.

### Scrabster ✅ DONE
- [x] Prices: HTML table at `scrabster.co.uk/port-information/fish-prices/`
- [ ] Landings: Don Fishing PDF — **TODO** (also covers Kinlochbervie)

### Fraserburgh — DORMANT
- [x] Prices scraper built but **SWFPA stopped publishing** Fraserburgh files as of March 2026. Scraper will auto-detect if they resume.
- [ ] Landings: **BLOCKED** — Google Drive PDF iframe. Needs Playwright or direct contact (enquiries@fraserburgh-harbour.co.uk).

### Not yet started
- [ ] **Kinlochbervie** — Don Fishing PDF (same source as Scrabster landings)
- [ ] **Lochinver** — no public data. Would need Highland Council contact.
- [ ] **Aberdeen** — market closed 2007, fish routes through Peterhead.

### Cross-cutting
- [ ] Species name normalisation across ports (e.g. "Monks" vs "Monkfish" vs "Monk Or Anglers")
- [ ] Don Fishing PDF scraper for Scrabster + Kinlochbervie landings
- [ ] Shetland detailed PDF scraper (grades + Scalloway port)

---

## Phase 3 — Daily Digest Report (IN PROGRESS)

**Goal**: Aggregate all ports into a single formatted daily report.

### HTML Digest ✅ DONE
- [x] Jinja2 template (`templates/digest.html`) — professional email-safe design
- [x] Header ticker — top price from each reporting port
- [x] Alert band — port count + species count
- [x] Price table — all species, all ports, grouped by species, best-price markers
- [x] Cross-port comparison bars — species at 2+ ports with visual bars
- [x] Auto-generated at end of pipeline → `output/digest_{date}.html`
- [x] Graceful empty state for no-data days

### Still TODO
- [ ] "Biggest movers" section (needs 2+ days of history for day-over-day)
- [ ] Email delivery (SMTP or SendGrid/Mailgun — template is ready)
- [ ] Subscriber list (start simple: config file of email addresses)

---

## Phase 4 — Dashboard & History

**Goal**: Web interface showing current + historical data.

- [ ] Static HTML dashboard (regenerated daily, hosted on S3/GitHub Pages)
- [ ] Price trend charts (species over time)
- [ ] Landing volume trends
- [ ] Cross-port comparison
- [ ] Historical data backfill (Peterhead has a date picker archive)

---

## Phase 5 — Commercial / API

**Goal**: Paid product for fish buyers, processors, merchants.

- [ ] API access (REST or simple webhook)
- [ ] Tiered subscriptions (basic email vs full API)
- [ ] Custom alerts (e.g. "notify me when Cod avg > £X")
- [ ] Integration with buyer systems
- [ ] Multi-port bundle pricing

---

## Project Foundations ✅ DONE

- [x] Git + GitHub (private repo, clean history)
- [x] CLAUDE.md project documentation
- [x] Ruff linter + formatter configured (pyproject.toml)
- [x] .gitignore (data/, output/, .env, IDE files, OS files)
- [x] Codebase fully lint-clean (0 issues)
- [x] pytest test suite (9 tests passing)

---

## Technical Notes

- Python 3.9+ (macOS system Python)
- SQLite for storage (`data/quayside.db`)
- launchd for scheduling (`~/Library/LaunchAgents/com.quayside.pipeline.plist`)
- All scrapers need User-Agent headers (403 without)
- SWFPA uses `var customQuery` (not `window.customQuery`) for event data
- Prices often lag landings by a day (SWFPA posts after auction)

---

## Partnership Strategy

**Short-term**: Scrape all publicly available ports (7 ports max in UK).

**Medium-term**: Partner with a fisheries media company for access to gated ports via revenue-share.
- **Fish Daily** (fishdaily.co.uk) — insider daily newsletter, likely has private data feeds
- **Undercurrent News** — already scrapes Peterhead + Brixham via Global Groundfish Price Tracker. Validates our model. Potential data licensing partner.

The scarcity of public port data IS the value proposition. Only ~7 of ~25-30 UK/Ireland auction ports publish anything publicly.
