# Quayside

UK fish auction price aggregator. Scrapes daily price and landing data from public sources across UK ports, normalizes it into a single SQLite database, and generates a daily HTML digest report. Also supports a port upload workflow where ports email price sheets that are AI-extracted and human-approved before publishing.

## Quick start

```bash
pip install -e ".[dev]"       # install with dev deps
python -m quayside            # run full pipeline (scrape → store → export → report)
python -m quayside --update   # ETag-aware intraday update (only re-scrapes changed sources)
pytest                        # run tests
```

## Architecture

```
src/quayside/
├── run.py              # Pipeline orchestrator — runs all scrapers, stores, exports, quality checks
├── db.py               # SQLite connection, schema, upsert, queries (~1200 lines)
├── models.py           # PriceRecord and LandingRecord dataclasses
├── export.py           # Per-port CSV export
├── email.py            # SMTP email delivery (env-var configured)
├── report.py           # Daily HTML digest generator (Jinja2, ~640 lines)
├── species.py          # Species name normalisation (raw → canonical) + category + noise filter (~314 lines)
├── ports.py            # Port registry — seeds/queries the ports table (16 ports defined)
├── ingest.py           # Email ingestion — polls IMAP mailbox for price sheet attachments
├── confirm.py          # HITL confirmation logic — token generation, approval, auto-publish
├── review.py           # Weekly/monthly review reports, sparkline SVG generation (~507 lines)
├── quality.py          # 11 data-quality checks (outliers, stale data, price sanity, etc.)
├── scheduler.py        # APScheduler background scheduler (runs inside web process)
├── trade.py            # Trade dashboard data — species-first cross-port intelligence
├── fx.py               # FX rate fetching from frankfurter.dev (for future multi-currency support)
├── template.py         # Upload template generation (per-port XLSX templates with validation)
├── http_cache.py       # ETag/Last-Modified/content-hash HTTP caching for intraday update runs
├── extractors/
│   ├── __init__.py     # Router: dispatch file to correct extractor by extension
│   ├── ai.py           # Claude API fallback extractor (claude-sonnet-4-6) for unknown formats
│   ├── csv_ext.py      # CSV price sheet extractor (auto-dialect, header detection)
│   ├── image.py        # Image extractor (PNG/JPG/HEIC — Claude Vision API)
│   ├── pdf.py          # PDF extractor (pdfplumber + AI fallback)
│   └── xls.py          # XLS/XLSX price sheet extractor (xlrd + openpyxl)
├── scrapers/
│   ├── swfpa.py        # SWFPA event page discovery + Peterhead XLS prices
│   ├── brixham.py      # Brixham prices (PDF via pdfplumber, regex row parsing)
│   ├── newlyn.py       # Newlyn prices (PDF via pdfplumber; CFPO fallback)
│   ├── scrabster.py    # Scrabster prices (HTML table from scrabster.co.uk)
│   ├── lerwick.py      # Lerwick/Shetland prices (XLSX from SSA web portal)
│   ├── cfpo.py         # CFPO PDF scraper (Newlyn fallback source)
│   └── fraserburgh.py  # Fraserburgh prices (dormant — SWFPA stopped publishing)
├── templates/
│   └── digest.html     # Email-safe digest template (standalone Jinja2)
└── web/
    ├── app.py          # Flask app factory, CSRF, security headers, context processors, error handlers
    ├── auth.py         # Authentication blueprint — login, register, logout, roles, magic links
    ├── public.py       # Public pages blueprint — landing, overview, for-ports, for-traders, about, methodology
    ├── port_views.py   # Port blueprint — dashboards, prices partial, upload, confirm, export, template, submit
    ├── trade_views.py  # Trade blueprint — trade dashboard, export, AI chat, ports directory, compare
    ├── ops_views.py    # Ops blueprint — ops dashboard, pipeline trigger, quality checks, quality report
    ├── api_views.py    # API blueprint — /api/v1/ingest (POST), /api/v1/export/csv (GET)
    ├── digest.py       # Digest blueprint — daily/weekly/monthly digest serving + email rendering
    ├── helpers.py      # Data processing helpers (~900 lines) — market position, trends, insights, categories
    ├── static/
    │   ├── css/tokens.css    # CSS design tokens (see BRAND.md)
    │   └── img/              # Marketing images (nets.jpg, pots.jpg, dashboard-preview.jpg)
    └── templates/            # 24 Jinja2 templates (see Pages section below)
```

## Data model

Tables in `data/quayside.db`:

- **prices**: date, port, species, grade, price_low, price_high, price_avg, weight_kg, boxes, defra_code, week_avg, size_band, upload_id
  - UNIQUE(date, port, species, grade)
- **demo_prices**: identical schema to prices — stores Demo Port synthetic data separately
- **landings**: date, port, vessel_name, vessel_code, species, boxes, boxes_msc
  - UNIQUE(date, port, vessel_name, vessel_code, species)
- **ports**: slug, name, code, region, data_method, status
  - Seeded on startup via `ports.py`; statuses: `active`, `outreach`, `future`; methods: `scraper`, `upload`, `demo`
- **uploads**: upload records for the port upload/HITL workflow
- **extraction_corrections**: corrections applied during AI extraction
- **scrape_log**: per-port scrape attempt timestamps and outcomes
- **quality_log**: issues logged by quality checks (unique index prevents duplicates)
- **users**: email, password_hash, role (TRADE, PORT_OPERATOR, ADMIN)

Upsert strategy: `INSERT OR REPLACE` — latest scrape wins for the same key. WAL pragma enabled for concurrency.

## Port registry

Defined in `ports.py` (`_SEED_PORTS`). Seeded on app startup.

| Status | Ports |
|---|---|
| **Active** (5) | Peterhead (PTH), Brixham (BRX), Newlyn (NLN), Lerwick (LWK), Scrabster (SCR) |
| **Demo** (1) | Demo Port (DEM) — synthetic data, isolated in `demo_prices` table |
| **Outreach** (6) | Fraserburgh (FRB), Kinlochbervie (KLB), Macduff (MCD), Eyemouth (EYE), Grimsby (GRM), Fleetwood (FLW) |
| **Future** (4) | Lowestoft (LOW), Whitby (WHT), Milford Haven (MLF), Kilkeel (KIL) |

## HARD RULE: Demo port isolation

The Demo Port (`slug='demo'`, `data_method='demo'`) exists solely to showcase the product. It uses **synthetic data** and must **never** appear in:

- The daily digest (any date)
- Port comparisons or cross-port benchmarks
- Trade dashboard data or port selector
- Quality checks or ops scrape alerts
- About page port listings or port counts
- Any market averages or aggregate stats

**How isolation is enforced:**
- Demo Port data lives in the separate `demo_prices` table — `prices` table only holds real data
- `get_all_prices_for_date()` only queries `prices`, so demo is excluded automatically
- When building port lists from `get_all_ports()`, always filter: `p.get("data_method") != "demo"`
- Use `slug != 'demo'` in templates as a belt-and-braces check

**If you add any new feature that lists ports, compares prices, or queries market data — you must explicitly exclude demo.** It keeps getting added back in by accident.

## Conventions

- **Scrapers return dataclass lists**: Every scraper returns `list[PriceRecord]` or `list[LandingRecord]`. No raw dicts.
- **Resilient pipeline**: Each scraper is wrapped in `_run_scraper()` which catches exceptions and returns `(results, error_info)`. One failing port doesn't kill the pipeline.
- **Species names are normalised at display time**: Raw names stored in DB exactly as scraped. `species.py` maps raw names to canonical names (e.g. "Monks" → "Monkfish") for cross-port comparison. Add new mappings to `_CANONICAL_MAP` in `species.py` when adding new ports.
- **Noise filtering**: `species.py` has `is_noisy_species()` which catches byproducts, offal, damaged fish, and Brixham concatenated suffixes (e.g., "Hadddam", "Megrimbru").
- **Grade systems differ by port**: Peterhead uses A1-A5, Brixham uses 1-10, Newlyn uses (1)-(15), Lerwick uses grades, Scrabster has none. The `grade` field stores whatever the source provides.
- **Dates are ISO 8601**: Always `YYYY-MM-DD` in the database and filenames.
- **Output goes to `output/`**: CSVs as `prices_{port}_{date}.csv`, digest as `digest_{date}.html`. This directory is gitignored.
- **Data goes to `data/`**: SQLite DB and uploaded files (`data/uploads/`). Also gitignored.
- **Port registry**: `ports.py` is the single source of truth for port slugs, codes, regions, and statuses. Do not hardcode port codes elsewhere.
- **Web app uses Flask blueprints**: Routes are split across 8 blueprint files in `web/`. `app.py` is the factory that registers them all.
- **helpers.py is the data engine**: All complex data processing for port dashboards lives in `web/helpers.py` (~900 lines). Functions like `build_today_data()`, `build_trend_data()`, `build_insights()`, `build_category_stats()`.

## Adding a new scraper

1. Create `src/quayside/scrapers/{port}.py`
2. Implement `scrape_prices() -> list[PriceRecord]` or `scrape_landings() -> list[LandingRecord]`
3. Add to `run.py` pipeline (import + `_run_scraper()` call + CSV export + `log_scrape_attempt()`)
4. Add port to `_SEED_PORTS` in `ports.py` with `data_method="scraper"` and `status="active"`
5. Add species name mappings to `_CANONICAL_MAP` in `species.py`
6. Test: `python -m quayside` then check `output/digest_*.html`

## Upload / HITL workflow

Ports that can't be scraped submit price sheets by email or web form:

1. Port emails a file (XLS/CSV/PDF/image) to the ingest mailbox
2. `ingest.py` polls via IMAP, identifies the port, routes the attachment to `extractors/`
3. Extractor parses the file; `ai.py` is the fallback for unknown formats (uses Claude API)
4. An upload record is created in the DB; a confirmation email is sent with a review link
5. Reviewer visits `/confirm/<token>` to approve or edit the extracted data
6. On approval, records are upserted into the prices table
7. Uploads pending > 2 hours are auto-published by `confirm.auto_publish_stale_uploads()`

Web upload via `/port/<slug>/upload` follows the same confirmation flow.

## Email delivery

Optional — only runs if environment variables are set:

```bash
export QUAYSIDE_SMTP_USER="you@gmail.com"
export QUAYSIDE_SMTP_PASS="your-app-password"
export QUAYSIDE_RECIPIENTS="buyer1@example.com,buyer2@example.com"
```

For Gmail, use an App Password (not your account password). The pipeline sends the digest automatically at the end of each run if configured.

Email ingestion (for port uploads) uses a separate IMAP config:

```bash
export QUAYSIDE_INGEST_HOST="imap.gmail.com"   # default
export QUAYSIDE_INGEST_PORT="993"               # default
export QUAYSIDE_INGEST_USER="prices@quayside.fish"
export QUAYSIDE_INGEST_PASS="app-password"
```

## Scheduling

Two scheduling mechanisms run in production:

**In-process (APScheduler via `scheduler.py`):**
- Runs inside the gunicorn web process
- Gunicorn must use a single worker (`--workers 1`) to avoid duplicate runs

**Systemd timers (production server):**
- `quayside-pipeline.timer` — every 10 minutes, weekdays 07:00–17:00 UTC
  - Smart logic in `deploy/run_pipeline.sh`: full run if no digest exists, ETag update check if data changed recently, hourly pulse otherwise
- `quayside-quality.timer` — backstop quality checks at 10:00, 13:00, 16:00 weekdays
  - Quality checks also run automatically at the end of every successful pipeline run

## Quality checks

`quality.py` runs 11 checks after every successful scrape and 3x daily as a backstop:

- Statistical: outlier prices (MAD), low record counts, stale data, daily avg spikes, seeded data detection, live-site smoke test
- Data accuracy: NULL/unknown fields, unmapped species, price sanity (<=0, >£200/kg, low>high), date sanity, price swings vs 30-day mean

Results are stored in `quality_log` table and surfaced at `/ops/quality-report`.

## Local development server

```bash
python -m quayside.web.app   # starts Flask at http://localhost:5000
```

Claude can connect to this via preview tools to take screenshots and inspect pages directly — no need to describe what you're looking at.

## Pages

Routes are served across 8 blueprint files registered in `src/quayside/web/app.py`:

| Route | Blueprint | Description |
|---|---|---|
| `/` | public | Landing page — ticker, marketing copy, port index |
| `/overview` | public | Market overview / staging hub with all screens |
| `/for-ports` | public | Marketing/onboarding page for port operators |
| `/for-traders` | public | Marketing page for fish merchants/traders |
| `/about` | public | About page — 3-tier explanation, port coverage table |
| `/methodology` | public | Data methodology documentation |
| `/login` | auth | Email/password login with role selection |
| `/register` | auth | Account creation (TRADE, PORT_OPERATOR, ADMIN roles) |
| `/logout` | auth | Logout |
| `/digest` | digest | Daily price digest (latest date) |
| `/digest/<date>` | digest | Daily price digest for a specific date (YYYY-MM-DD) |
| `/digest/yesterday` · `/digest/today` | digest | Convenience redirects |
| `/digest/weekly` · `/digest/weekly/<date>` | digest | Weekly 5-day review with movers, spreads, heatmap |
| `/digest/monthly` · `/digest/monthly/<year_month>` | digest | Monthly trend report with volatility, availability matrix |
| `/port/<slug>` | port | Individual port dashboard — prices, trends, insights, categories |
| `/port/<slug>/prices` | port | Prices partial (AJAX endpoint for date switching) |
| `/port/<slug>/api/ranking` | port | Port ranking API (JSON) |
| `/port/<slug>/api/compare` | port | Cross-port species comparison API (JSON) |
| `/port/<slug>/upload` | port | Upload form — file upload, form entry, or template download |
| `/port/<slug>/export` | port | Download CSV of port price data (365-day history) |
| `/port/<slug>/template` | port | Download XLSX upload template for a port |
| `/port/submit` or `/port/<slug>/submit` | port | Port signup/contact form (no auth required) |
| `/confirm/<token>` | port | HITL confirmation page — review extracted price data |
| `/confirm/<token>/approve` | port | Approve confirmed upload (POST) |
| `/confirm/<token>/edit` | port | Edit extracted data before approving |
| `/ops` | ops | Internal ops dashboard — scrape status, pipeline health, upload queue |
| `/ops/run-pipeline` | ops | Trigger pipeline manually (POST, 5-min timeout) |
| `/ops/run-quality-check` | ops | Trigger quality checks manually (POST) |
| `/ops/quality/clear/<id>` | ops | Clear a quality issue (POST) |
| `/ops/quality-report` | ops | Quality report page |
| `/ops/quality-report/download` | ops | Download quality report as markdown |
| `/trade` · `/trade/<date>` | trade | Trade dashboard — species-first cross-port matrix (auth required) |
| `/trade/export` | trade | Export trade data as CSV (90-day default) |
| `/trade/ports` | trade | Port contacts directory with auction times |
| `/trade/feedback` | trade | Trade dashboard feedback (POST) |
| `/trade/compare` | trade | Cross-port species comparison matrix (JSON) |
| `/trade/chat` | trade | Claude Haiku AI chatbot endpoint (POST, max 400 tokens) |
| `/api/v1/ingest` | api | API endpoint for price data ingestion (POST, API key auth) |
| `/api/v1/export/csv` | api | API endpoint for bulk CSV export (GET, filter by port/date/species) |

### Templates (24 files in `web/templates/`)

| Template | Used by |
|---|---|
| `base.html` | All pages — master layout with nav, ticker, footer |
| `landing.html` | `/` — full marketing homepage |
| `index.html` | `/overview` — staging hub with card grid |
| `about.html` | `/about` |
| `for_ports.html` | `/for-ports` |
| `for_traders.html` | `/for-traders` |
| `methodology.html` | `/methodology` |
| `login.html` | `/login` |
| `register.html` | `/register` |
| `dashboard.html` | `/port/<slug>` — main port dashboard |
| `prices_partial.html` | `/port/<slug>/prices` — AJAX prices table |
| `upload_form.html` | `/port/<slug>/upload` |
| `confirm.html` | `/confirm/<token>` |
| `edit.html` | `/confirm/<token>/edit` |
| `submit.html` | `/port/submit` |
| `digest_wrapper.html` | `/digest` — wraps email digest template |
| `weekly.html` | `/digest/weekly` |
| `monthly.html` | `/digest/monthly` |
| `trade.html` | `/trade` — species matrix, sidebar nav |
| `trade_gate.html` | Trade paywall (£95/month) |
| `trade_ports.html` | `/trade/ports` |
| `ops.html` | `/ops` |
| `quality_report.html` | `/ops/quality-report` |
| `error.html` | 404/500 error pages |

## Git workflow

- For quick iteration sessions, committing directly to `main` is fine — GitHub Actions auto-deploys on push.
- For larger features, use a branch like `feature/short-description` and merge after verification (ruff, pytest, visual check).

## Deployment

The live site is at **https://quaysidedata.duckdns.org/**. It is deployed automatically via GitHub Actions on every push to `main`.

**To deploy changes to the live site**: commit changes and push to `main` — GitHub Actions auto-deploys on push to `main`. There is no manual deploy step.

### Infrastructure

- **Hosting provider**: Hetzner (cloud.hetzner.com)
- **Server IP**: `46.62.148.67`
- **SSH user**: `root`
- **App location on server**: `/home/quayside/app/`
- **Deploy script**: `/home/quayside/app/deploy/update.sh`
- **GitHub Actions secret**: `SSH_PRIVATE_KEY` — must match the public key in `/root/.ssh/authorized_keys` on the server
- **Web server**: nginx reverse proxy → gunicorn (unix socket) → Flask
- **Process manager**: systemd (`quayside.service`)
- **Pipeline scheduling**: systemd timers (`quayside-pipeline.timer`, `quayside-quality.timer`)
- **Logs**: `/var/log/quayside/` (access, error, pipeline, quality)

### Fixing broken deployments

If GitHub Actions SSH deployment fails with `unable to authenticate` / `no supported methods remain`:

**Important:** The Hetzner browser console cannot reliably paste special characters (`>`, `|`). Do NOT try to write files via the console — use Rescue Mode instead.

1. On Mac: `ssh-keygen -t ed25519 -f ~/github_deploy_key -N ""` to generate a key pair (skip if `~/github_deploy_key` already exists)
2. Go to **cloud.hetzner.com** → your server → **Rescue** tab
3. Paste the contents of `deploy/authorized_keys` (committed to the repo) into the SSH key field
4. Click **"Enable Rescue & Power Cycle"** — note the rescue password shown
5. On Mac: `ssh-keygen -R 46.62.148.67` to clear old host key, then `ssh -i ~/github_deploy_key root@46.62.148.67` (use rescue password if prompted)
6. In rescue shell: `mount /dev/sda1 /mnt`
7. In rescue shell: `mkdir -p /mnt/root/.ssh && echo "$(cat ~/.ssh/authorized_keys 2>/dev/null || cat /root/.ssh/authorized_keys)" > /mnt/root/.ssh/authorized_keys` — OR paste the public key manually:
   `echo "ssh-ed25519 AAAA..." > /mnt/root/.ssh/authorized_keys && chmod 700 /mnt/root/.ssh && chmod 600 /mnt/root/.ssh/authorized_keys`
8. `reboot` in the rescue shell
9. On Mac: `ssh-keygen -R 46.62.148.67` again, then `ssh -i ~/github_deploy_key root@46.62.148.67` to verify access
10. Update GitHub secret: repo → Settings → Secrets → Actions → `SSH_PRIVATE_KEY` → paste contents of `~/github_deploy_key`
11. Push any commit to `main` to trigger a test deploy

## Key docs

- `BRAND.md` — full brand kit: colour palette, typography, design principles, component patterns
- `PORTS.md` — comprehensive audit of all UK & Ireland fish ports, data availability, partnership strategy
- `ROADMAP.md` — development phases and status
