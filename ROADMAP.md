# Quayside — Roadmap

UK fish auction data pipeline. Scrapes landings + prices, stores in SQLite, delivers daily reports.

---

## Phase 1 — Peterhead Pipeline [DONE]

**Goal**: Scrape Peterhead landings + prices daily, store & export CSVs.

- [x] Landings scraper (peterheadport.co.uk HTML table)
- [x] Price scraper (SWFPA daily XLS via calendar discovery)
- [x] SQLite storage with upsert (no duplicates)
- [x] CSV export (landings + prices)
- [x] launchd scheduled at 10:15 AM weekdays
- [x] Tests with saved fixtures (9 passing)

**Data sources**:
- Landings: `https://www.peterheadport.co.uk/fish-auction/` — vessels, species, boxes (regular + MSC)
- Prices: SWFPA XLS via `https://swfpa.com/downloads/daily-fish-prices/` — £/kg per species per grade

**Known risk**: Peterhead launching new E-Auction system March 31, 2026. Scraper may need updating.

---

## Phase 2 — More Ports

**Goal**: Expand beyond Peterhead to other Scottish ports.

### Lerwick (Shetland) — IN PROGRESS
- [x] Landings: `shetlandauction.com/ssa-today` — clean HTML table, 83 records/day
- [ ] Prices: **BLOCKED** — requires login to Kosmos auction system or SSA Web Portal. No public price feed. Contact norma@shetlandauction.com to request access.

### Brixham (Devon) — DONE
- [x] Prices: SWFPA daily PDF (`Daily-Fish-Sales-Report-N.pdf`) on same event page as Peterhead XLS. Parsed with pdfplumber. Format: `SPECIES [GRADE] DEFRA_CODE WEIGHT DAY_AVG WEEK_AVG`. Only day average price (no low/high split).
- [ ] Landings: Not available via SWFPA or public web. Brixham Fish Market is privately operated (BrixhamFish Ltd). Would need direct contact.

### Fraserburgh — IN PROGRESS
- [ ] Landings: **BLOCKED** — page embeds a Google Drive PDF iframe, not an HTML table. Needs Playwright/Selenium or direct contact with harbour for a data feed. Email: enquiries@fraserburgh-harbour.co.uk
- [ ] Prices: **BLOCKED** — SWFPA hosted HTML price files historically (pattern: `swfpa.com/wp-content/uploads/YYYY/MM/Fraserburgh-DD.MM.html`) but as of March 2026 they are not linked from the calendar and appear to no longer be published. Scraper is in place and will pick them up automatically if SWFPA resumes. Only a single price per species (no low/high/avg split like Peterhead).

### Aberdeen
- [ ] **SKIP** — Aberdeen Fish Market closed 2007. Fish routes through Peterhead.

### Scrabster
- [ ] Prices: partial HTML at `scrabster.co.uk/port-information/fish-prices/` — prices per kg but thin data, no SWFPA XLS. Lower priority.
- [ ] Landings: FIS integration (`seafood.media/fis/marketprices/prices.asp?marketid=07`) — needs investigation.

### Lochinver
- [ ] **DEFERRED** — no public data source. Annual stats only from Marine Scotland. Would need direct contact with Highland Council harbours.

---

**For each remaining port:**
- Find landings data source (website, PDF, or other)
- Check if SWFPA covers their prices (the XLS page may have sheets for other ports)
- Build scraper, add to pipeline
- Normalise species names across ports

---

## Phase 3 — Daily Email Report

**Goal**: Aggregate all ports into a single formatted morning email.

- [ ] HTML email template — clean tables, mobile-friendly
- [ ] Landings summary per port: total boxes by species, vessel count
- [ ] Price summary per port: species, grade, low/high/avg in £/kg
- [ ] Cross-port comparison (same species, different ports)
- [ ] Price movement: vs yesterday / vs week avg (once we have history)
- [ ] Email delivery (SMTP or SendGrid/Mailgun)
- [ ] Add to daily launchd pipeline (scrape all ports → store → email)
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

## Technical Notes

- Python 3.9+ (macOS system Python)
- SQLite for storage (`data/quayside.db`)
- launchd for scheduling (`~/Library/LaunchAgents/com.quayside.pipeline.plist`)
- All scrapers need User-Agent headers (403 without)
- SWFPA uses `var customQuery` (not `window.customQuery`) for event data
- Prices often lag landings by a day (SWFPA posts after auction)
