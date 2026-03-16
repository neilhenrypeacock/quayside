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

## Local development server

```bash
python -m quayside.web.app   # starts Flask at http://localhost:5000
```

Claude can connect to this via preview tools to take screenshots and inspect pages directly — no need to describe what you're looking at.

## Pages

All routes served by `src/quayside/web/app.py`:

| Route | Description |
|---|---|
| `/` | Homepage — port index, links to all port dashboards |
| `/overview` | Market overview across all ports |
| `/for-ports` | Marketing/onboarding page for port operators |
| `/digest` | Daily price digest (latest date) |
| `/digest/<date>` | Daily price digest for a specific date (YYYY-MM-DD) |
| `/digest/weekly` | Weekly digest (latest) |
| `/digest/weekly/<date>` | Weekly digest for specific week |
| `/digest/monthly` | Monthly digest (latest) |
| `/digest/monthly/<year_month>` | Monthly digest e.g. `/digest/monthly/2026-03` |
| `/port/<slug>` | Individual port dashboard — prices history, species breakdown, benchmarks |
| `/port/<slug>/upload` | Upload form for port operators to submit price data |
| `/confirm/<token>` | HITL confirmation page — review extracted price data before approving |
| `/confirm/<token>/approve` | Approve confirmed upload (POST) |
| `/confirm/<token>/edit` | Edit extracted data before approving |
| `/ops` | Internal ops dashboard — scrape status, pipeline health, upload queue |
| `/port/<slug>/export` | Download CSV of port price data |
| `/port/<slug>/template` | Download upload template for a port |
| `/port/submit` or `/port/<slug>/submit` | Port signup/contact form |

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

- `PORTS.md` — comprehensive audit of all UK & Ireland fish ports, data availability, partnership strategy
- `ROADMAP.md` — development phases and status
