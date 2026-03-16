# Quayside

UK fish auction price aggregator. Scrapes daily price and landing data from public sources across UK ports, normalizes it into a single SQLite database, and generates a daily HTML digest report.

## Quick start

```bash
pip install -e ".[dev]"       # install with dev deps
python -m quayside            # run full pipeline (scrape → store → export → report)
pytest                        # run tests
```

## Architecture

```
src/quayside/
├── run.py              # Pipeline orchestrator — runs all scrapers, stores, exports
├── db.py               # SQLite connection, schema, upsert, queries
├── models.py           # PriceRecord and LandingRecord dataclasses
├── export.py           # Per-port CSV export
├── email.py            # SMTP email delivery (env-var configured)
├── report.py           # Daily HTML digest generator (Jinja2)
├── species.py          # Species name normalisation (raw → canonical)
├── templates/
│   └── digest.html     # Jinja2 template for the daily digest
└── scrapers/
    ├── swfpa.py        # SWFPA event page discovery + Peterhead XLS prices
    ├── peterhead.py    # Peterhead landings (HTML table)
    ├── brixham.py      # Brixham prices (PDF via pdfplumber)
    ├── newlyn.py       # Newlyn prices (PDF via pdfplumber)
    ├── scrabster.py    # Scrabster prices (HTML table)
    ├── lerwick.py      # Lerwick/Shetland landings (HTML table)
    └── fraserburgh.py  # Fraserburgh prices (dormant — SWFPA stopped publishing)
```

## Data model

Two tables in `data/quayside.db`:

- **prices**: date, port, species, grade, price_low, price_high, price_avg
  - UNIQUE(date, port, species, grade)
- **landings**: date, port, vessel_name, vessel_code, species, boxes, boxes_msc
  - UNIQUE(date, port, vessel_name, vessel_code, species)

Upsert strategy: `INSERT OR REPLACE` — latest scrape wins for the same key.

## Conventions

- **Scrapers return dataclass lists**: Every scraper returns `list[PriceRecord]` or `list[LandingRecord]`. No raw dicts.
- **Resilient pipeline**: Each scraper is wrapped in `_run_scraper()` which catches exceptions. One failing port doesn't kill the pipeline.
- **Species names are normalised at display time**: Raw names stored in DB exactly as scraped. `species.py` maps raw names to canonical names (e.g. "Monks" → "Monkfish") for cross-port comparison in the digest report. Add new mappings to `_CANONICAL_MAP` in `species.py` when adding new ports.
- **Grade systems differ by port**: Peterhead uses A1-A5, Brixham uses 1-10, Scrabster has none. The `grade` field stores whatever the source provides.
- **Dates are ISO 8601**: Always `YYYY-MM-DD` in the database and filenames.
- **Output goes to `output/`**: CSVs as `prices_{port}_{date}.csv`, digest as `digest_{date}.html`. This directory is gitignored.
- **Data goes to `data/`**: SQLite DB. Also gitignored.

## Adding a new scraper

1. Create `src/quayside/scrapers/{port}.py`
2. Implement `scrape_prices() -> list[PriceRecord]` or `scrape_landings() -> list[LandingRecord]`
3. Add to `run.py` pipeline (import + `_run_scraper()` call + CSV export)
4. Add port code to `PORT_CODES` dict in `report.py`
5. Add species name mappings to `_CANONICAL_MAP` in `species.py`
6. Test: `python -m quayside` then check `output/digest_*.html`

## Email delivery

Optional — only runs if environment variables are set:

```bash
export QUAYSIDE_SMTP_USER="you@gmail.com"
export QUAYSIDE_SMTP_PASS="your-app-password"
export QUAYSIDE_RECIPIENTS="buyer1@example.com,buyer2@example.com"
```

For Gmail, use an App Password (not your account password). The pipeline sends the digest automatically at the end of each run if configured.

## Scheduling

Pipeline runs weekdays at 10:15 AM via macOS launchd. Plist at `com.quayside.pipeline.plist`.

## Git workflow

- **Always work on a feature branch** — never commit directly to `main`. Create a branch like `feature/short-description` at the start of each session.
- Merge to `main` only after verification passes (ruff, pytest, visual check).

## Deployment

The live site is at **https://quaysidedata.duckdns.org/**. It is deployed automatically via GitHub Actions on every push to `main`.

**To deploy changes to the live site**: commit changes and push to `main` — GitHub Actions auto-deploys on push to `main`. There is no manual deploy step.

## Key docs

- `PORTS.md` — comprehensive audit of all UK & Ireland fish ports, data availability, partnership strategy
- `ROADMAP.md` — development phases and status
