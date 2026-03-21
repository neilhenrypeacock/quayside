# Quayside — Complete AI Context File

## IDENTITY

**Name:** Quayside
**Type:** UK fish auction price aggregator — B2B SaaS / data intelligence platform
**Stack:** Python 3 / Flask / SQLite / Jinja2 / APScheduler / Claude API
**Status:** Live in production at https://quaysidedata.duckdns.org/
**Purpose:** Scrapes daily price and landing data from public sources across UK fish auction ports, normalises it into a single SQLite database, and generates daily HTML digest reports. Also supports a port upload workflow (HITL) where ports email price sheets that are AI-extracted and human-approved before publishing. Provides port operator dashboards and a paid trade intelligence product for fish merchants.

---

## FULL TECH STACK

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3 | ~12,800 lines across 44+ files |
| Web framework | Flask | Blueprints, CSRF, WTForms |
| Database | SQLite (WAL mode) | `data/quayside.db` |
| ORM | Raw SQL via `sqlite3` | No ORM — parameterised queries throughout |
| Templates | Jinja2 | 30 templates in `web/templates/`, 1 standalone |
| CSS | Custom design tokens | `tokens.css` — cool-neutral palette |
| Fonts | Google Fonts CDN | Playfair Display, IBM Plex Sans, IBM Plex Mono |
| Scheduling | APScheduler (in-process) + systemd timers | Pipeline runs every 10 min weekdays |
| PDF parsing | pdfplumber | Used in Brixham, Newlyn, CFPO scrapers |
| Spreadsheet | xlrd + openpyxl | XLSX/XLS price sheets |
| AI extraction | Claude API (claude-sonnet-4-6) | Fallback extractor for unknown formats |
| AI chatbot | Claude API (claude-haiku-4-5) | Port + trade AI chat, max 400 tokens |
| HTTP caching | ETag/Last-Modified/content-hash | `http_cache.py` |
| Email delivery | SMTP (smtplib) | Optional; Gmail App Password |
| Email ingestion | IMAP (imaplib) | Polls mailbox for port price sheets |
| FX rates | frankfurter.dev API | `fx.py` |
| Auth | Flask session + bcrypt | Roles: TRADE, PORT_OPERATOR, ADMIN |
| CSRF | Flask-WTF | All state-mutating routes protected |
| Deployment | Hetzner VPS + nginx + gunicorn | GitHub Actions CI/CD on push to main |
| Process manager | systemd | `quayside.service` |

---

## FILE STRUCTURE

```
quayside/
├── CLAUDE.md               # Claude Code working memory
├── claudechat.md           # This file — AI context for Claude.ai
├── HEALTH_AUDIT.md         # 15-page security/quality audit (2026-03-20)
├── BRAND.md                # Brand kit (typography, design principles — warm palette, outdated)
├── PORTS.md                # UK & Ireland port audit, partnership strategy
├── ROADMAP.md              # Development phases and status
├── scripts/
│   └── generate_context.py # Pre-commit hook: updates line counts + git log in claudechat.md
├── deploy/
│   ├── quayside.service    # systemd service unit
│   ├── quayside.timer      # systemd timer (pipeline)
│   ├── run_pipeline.sh     # Smart pipeline runner (full/update/pulse logic)
│   └── update.sh           # Deploy script (git pull, pip install, systemctl restart)
├── tests/
│   └── test_swfpa.py       # 5 tests for SWFPA scraper
└── src/quayside/
    ├── __main__.py         # Entry point: python -m quayside
    ├── run.py              # Pipeline orchestrator — scrape → store → export → quality (519 lines)
    ├── db.py               # SQLite connection, schema, upsert, queries (1449 lines)
    ├── models.py           # PriceRecord and LandingRecord dataclasses (32 lines)
    ├── export.py           # Per-port CSV export (33 lines)
    ├── email.py            # SMTP email delivery, env-var configured (83 lines)
    ├── report.py           # Daily HTML digest generator, Jinja2 (831 lines)
    ├── species.py          # Species name normalisation + category + noise filter (313 lines)
    ├── ports.py            # Port registry — seeds/queries the ports table, 16 ports (76 lines)
    ├── ingest.py           # Email ingestion — polls IMAP mailbox for price sheets (225 lines)
    ├── confirm.py          # HITL confirmation — token generation, approval, auto-publish (190 lines)
    ├── review.py           # Weekly/monthly review reports, sparkline SVGs (504 lines)
    ├── quality.py          # 11 data-quality checks (outliers, stale data, price sanity) (1104 lines)
    ├── scheduler.py        # APScheduler background scheduler, runs inside web process (143 lines)
    ├── trade.py            # Trade dashboard data — species-first cross-port intelligence (907 lines)
    ├── fx.py               # FX rate fetching from frankfurter.dev (70 lines)
    ├── template.py         # Upload template generation (per-port XLSX with validation) (163 lines)
    ├── http_cache.py       # ETag/Last-Modified/content-hash HTTP caching (126 lines)
    ├── error_actions.py    # Error dashboard fix actions, plain-English explanations (289 lines)
    ├── extractors/
    │   ├── __init__.py     # Router: dispatch file to correct extractor by extension (0 lines)
    │   ├── ai.py           # Claude API fallback extractor (claude-sonnet-4-6) (130 lines)
    │   ├── csv_ext.py      # CSV price sheet extractor (auto-dialect, header detection) (87 lines)
    │   ├── image.py        # Image extractor (PNG/JPG/HEIC — Claude Vision API) (117 lines)
    │   ├── pdf.py          # PDF extractor (pdfplumber + AI fallback) (97 lines)
    │   └── xls.py          # XLS/XLSX price sheet extractor (xlrd + openpyxl) (165 lines)
    ├── scrapers/
    │   ├── swfpa.py        # SWFPA event page discovery + Peterhead XLS prices (256 lines)
    │   ├── brixham.py      # Brixham prices (PDF via pdfplumber, regex row parsing) (174 lines)
    │   ├── newlyn.py       # Newlyn prices (PDF via pdfplumber; CFPO fallback) (201 lines)
    │   ├── scrabster.py    # Scrabster prices (HTML table from scrabster.co.uk) (147 lines)
    │   ├── lerwick.py      # Lerwick/Shetland prices (XLSX from SSA web portal) (179 lines)
    │   ├── cfpo.py         # CFPO PDF scraper (Newlyn fallback source) (77 lines)
    │   └── fraserburgh.py  # Fraserburgh prices (dormant — SWFPA stopped publishing) (161 lines)
    ├── templates/
    │   └── digest.html     # Email-safe digest template (standalone Jinja2, 1437 lines)
    └── web/
        ├── app.py          # Flask app factory, CSRF, security headers, context processors (172 lines)
        ├── auth.py         # Authentication blueprint — login, register, logout, roles (122 lines)
        ├── public.py       # Public pages — landing, overview, for-ports, for-traders, about (137 lines)
        ├── port_views.py   # Port blueprint — dashboards, upload, confirm, export, chat, onboarding (865 lines)
        ├── trade_views.py  # Trade blueprint — trade dashboard, export, AI chat, compare (310 lines)
        ├── ops_views.py    # Ops blueprint — ops dashboard, pipeline, quality, errors (873 lines)
        ├── api_views.py    # API blueprint — /api/v1/ingest (POST), /api/v1/export/csv (GET) (200 lines)
        ├── digest.py       # Digest blueprint — daily/weekly/monthly digest serving (86 lines)
        ├── helpers.py      # Data processing engine — market position, trends, insights (1474 lines)
        ├── static/
        │   ├── css/tokens.css    # CSS design tokens — cool-neutral palette (1089 lines)
        │   └── img/              # Marketing images (nets.jpg, pots.jpg, dashboard-preview.jpg)
        └── templates/            # 30 Jinja2 templates (~19,500 lines total)
```

---

## SCREENS & PAGES (EXHAUSTIVE)

### Public Pages

**`/` — Landing page** (`landing.html`, 1494 lines)
- Full marketing homepage for potential subscribers and port operators
- Sections: hero with scrolling price ticker, live market snapshot, feature highlights (port dashboard demo, trade intelligence), port coverage map, testimonials, pricing tiers, CTA
- Data: ticker (last 20 price records across active ports), stat strip (4 KPIs: ports covered, species tracked, records today, avg price), live price samples
- Nav in: direct URL / links
- Nav out: /login, /register, /for-ports, /for-traders, /port/demo

**`/overview` — Staging hub** (`index.html`, 244 lines)
- Card grid of all major product screens for internal navigation / demos
- Data: none (static links)
- Nav out: all major routes

**`/for-ports` — Port operators marketing** (`for_ports.html`, 867 lines)
- Marketing/onboarding page explaining the free port dashboard offering
- Sections: value prop, how it works (upload workflow), sample dashboard, signup CTA
- Nav out: /port/submit, /login, /register

**`/for-traders` — Traders/merchants marketing** (`for_traders.html`, 2022 lines)
- Marketing page for fish merchants explaining the trade intelligence product
- Sections: species matrix demo, cross-port comparison, price alerts, pricing (£95/month)
- Nav out: /login, /register, /trade (demo)

**`/about` — About page** (`about.html`, 722 lines)
- 3-tier explanation (scrapers → HITL → trade), port coverage table (active ports only, demo excluded)
- Lists 5 active ports with region and data method

**`/methodology` — Data methodology** (`methodology.html`, 179 lines)
- Technical explanation of data collection, normalisation, quality checks, grade systems

### Auth Pages

**`/login` — Login** (`login.html`, 208 lines)
- Email + password form with role selector (TRADE / PORT_OPERATOR / ADMIN)
- Redirects to appropriate dashboard on success

**`/register` — Register** (`register.html`, 214 lines)
- Account creation — name, email, password, role selector
- TRADE and PORT_OPERATOR roles are user-selectable; ADMIN must be set in DB

**`/logout`** — Clears session, redirects to `/`

### Digest Pages

**`/digest` and `/digest/<date>` — Daily digest** (`digest_wrapper.html`, 131 lines)
- Wraps the standalone email-safe `digest.html` template in a web frame
- Shows all active ports' prices for the given date, species breakdown, highlights
- Data: all price records for date (demo excluded), quality annotations

**`/digest/yesterday` · `/digest/today`** — Redirect shortcuts

**`/digest/weekly` · `/digest/weekly/<date>` — Weekly review** (`weekly.html`, 486 lines)
- 5-day market review: movers, spreads, species availability heatmap, sparklines
- Data: 5 most recent trading days, port comparisons

**`/digest/monthly` · `/digest/monthly/<year_month>` — Monthly report** (`monthly.html`, 513 lines)
- Monthly trend report: species availability matrix, price volatility, top/bottom performers
- Data: full month's records, 30-day averages

### Port Dashboard Pages

**`/port/<slug>` — Port dashboard** (`dashboard.html`, 3597 lines)
- Main port operator and subscriber view
- Layout: immersive — simplified top nav (`_nav_dashboard.html`), sidebar with section links, main content area
- Sections:
  - Stat strip: today's prices, weekly avg, volume, species count
  - Today's prices table (sortable by species/grade/price)
  - Competitive positioning: market rank, price vs network avg
  - Price trends: 30-day sparklines per species
  - Category breakdown (demersal, pelagic, shellfish)
  - Smart alerts (outliers, stale data, species missing)
  - Info-tips throughout with plain-English explanations
  - How-to drawer (`_howto_drawer.html`) — guided tour for new users
  - Floating AI chat FAB (`_chat_float.html`)
- Data: `build_today_data()`, `build_trend_data()`, `build_insights()`, `build_category_stats()`, `build_competitive_market()`, `build_smart_alerts()`, `build_stat_strip_data()` from `helpers.py`
- Auth: public for demo port; PORT_OPERATOR or ADMIN for real ports (or magic link token)

**`/port/<slug>/prices` — Prices partial** (`prices_partial.html`, 151 lines)
- AJAX endpoint for date switching on the dashboard
- Returns just the prices table HTML fragment
- Data: price records for selected date

**`/port/<slug>/onboarding` — Onboarding flow** (`onboarding.html`, 443 lines)
- First-time port operator welcome experience
- Sections: welcome screen, data upload walkthrough, guided dashboard tour
- Includes `_howto_drawer.html` for interactive guidance
- POST `/port/<slug>/onboarding/complete` marks onboarding as done

**`/port/<slug>/upload` — Upload form** (`upload_form.html`, 166 lines)
- File upload (drag-drop + browse) for price sheets (XLS/CSV/PDF/image)
- Also supports manual form entry
- Links to XLSX template download
- Triggers HITL workflow on submit

**`/confirm/<token>` — HITL confirmation** (`confirm.html`, 94 lines)
- Reviewer sees extracted price data in a table before publishing
- Approve or Edit actions

**`/confirm/<token>/edit` — Edit upload** (`edit.html`, 98 lines)
- Inline editing of extracted rows before approving

**`/port/submit` · `/port/<slug>/submit` — Port signup form** (`submit.html`, 474 lines)
- Contact/signup form for ports wanting to join the network
- No auth required — public lead capture

**`/port/<slug>/api/ranking`** — JSON: port ranking by avg price vs network
**`/port/<slug>/api/compare`** — JSON: cross-port species comparison
**`/port/<slug>/export`** — CSV download: 365-day price history
**`/port/<slug>/template`** — XLSX download: upload template for the port
**`/port/<slug>/chat`** — POST: port-scoped AI chatbot (Claude Haiku)

### Trade Dashboard Pages

**`/trade` · `/trade/<date>` — Trade dashboard** (`trade.html`, 3420 lines)
- Species-first cross-port intelligence matrix for fish merchants
- Layout: sidebar nav (species categories), main matrix table, detail panel
- Sections:
  - Species matrix: rows=species, cols=ports, cells=price/volume/grade
  - Widest spread: volume-weighted avg + min 2 grades filter
  - Watchlist (starred species/ports)
  - Cross-port comparison charts
  - AI chat for market questions
  - Floating chat FAB (`_chat_float.html`)
- Data: `trade.py` functions, FX rates from `fx.py`
- Auth: token-gated (£95/month subscription)

**`/trade/export`** — CSV: 90-day cross-port species data
**`/trade/ports`** — Port contacts directory with auction times (`trade_ports.html`, 314 lines)
**`/trade/feedback`** — POST: feedback submission
**`/trade/compare`** — JSON: cross-port species comparison matrix
**`/trade/chat`** — POST: Claude Haiku AI chatbot (max 400 tokens)

### Ops Dashboard Pages

**`/ops` — Ops dashboard** (`ops.html`, 1104 lines)
- Internal operations view: scraper health, port status, pipeline controls, upload queue
- Sections: scrape log (last run per port, success/fail), pipeline trigger button, quality alerts, upload queue (pending HITL items)
- Auth: currently unauthenticated (HEALTH_AUDIT critical finding)

**`/ops/quality-report`** — Quality report page (`quality_report.html`, 592 lines)
**`/ops/quality-report/download`** — Markdown export
**`/ops/errors`** — Error dashboard (`errors.html`, 546 lines): plain-English explanations + one-click fixes
**`/ops/errors/scan`** — POST: trigger quality scan
**`/ops/errors/fix/<id>`** — POST: apply auto-fix
**`/ops/errors/fix-all`** — POST: fix all auto-fixable
**`/ops/errors/download`** — Markdown export
**`/ops/run-pipeline`** — POST: trigger full pipeline (5-min timeout)
**`/ops/run-quality-check`** — POST: trigger quality checks
**`/ops/quality/clear/<id>`** — POST: clear quality issue
**`/ops/quality/clear-all`** — POST: clear all quality issues

### API Endpoints

**`POST /api/v1/ingest`** — Accept JSON price submissions (API key auth via `QUAYSIDE_API_KEY`)
**`GET /api/v1/export/csv`** — Bulk CSV export with filters (port, date range, species)

---

## COMPONENT INVENTORY (TEMPLATES)

| Template | Lines | Type | Purpose & Key Elements |
|---|---|---|---|
| `base.html` | 166 | Layout | Master layout: sticky nav, ticker, stat strip, content block, flash messages |
| `landing.html` | 1494 | Page | Full marketing homepage with hero, features, pricing, CTA sections |
| `index.html` | 244 | Page | Staging hub card grid for internal navigation |
| `about.html` | 722 | Page | 3-tier explainer, port coverage table (active ports only) |
| `for_ports.html` | 867 | Page | Port operator marketing and upload workflow explainer |
| `for_traders.html` | 2022 | Page | Trader/merchant marketing with species matrix demo |
| `methodology.html` | 179 | Page | Data methodology and grade system documentation |
| `login.html` | 208 | Page | Email/password login with role selector |
| `register.html` | 214 | Page | Account creation form |
| `dashboard.html` | 3597 | Page | Port dashboard — prices, trends, insights, competitive, onboarding |
| `prices_partial.html` | 151 | Partial | AJAX prices table fragment for date switching |
| `onboarding.html` | 443 | Page | First-time port operator welcome + guided tour |
| `upload_form.html` | 166 | Page | Price sheet file upload + manual entry form |
| `confirm.html` | 94 | Page | HITL review — extracted data table with approve/edit |
| `edit.html` | 98 | Page | Inline edit extracted rows before approving |
| `submit.html` | 474 | Page | Port signup/contact form (no auth) |
| `digest_wrapper.html` | 131 | Layout | Web wrapper for email-safe digest template |
| `weekly.html` | 486 | Page | 5-day weekly review report |
| `monthly.html` | 513 | Page | Monthly trend report |
| `trade.html` | 3420 | Page | Species-first cross-port trade intelligence matrix |
| `trade_gate.html` | 25 | Page | Trade dashboard paywall (£95/month) |
| `trade_ports.html` | 314 | Page | Port contacts directory with auction times |
| `ops.html` | 1104 | Page | Ops dashboard — scraper health, pipeline, quality, uploads |
| `quality_report.html` | 592 | Page | Quality report with issue list and status |
| `errors.html` | 546 | Page | Error dashboard with plain-English explanations and fix actions |
| `error.html` | 11 | Page | Generic 404/500 error page |
| `_chat_float.html` | 126 | Partial | Floating AI chat FAB (included in dashboard + trade) |
| `_howto_drawer.html` | 274 | Partial | Slide-in how-to guidance drawer for onboarding |
| `_nav_dashboard.html` | 39 | Partial | Simplified top nav bar for immersive dashboard mode |
| `digest.html` (in `templates/`) | 1437 | Email | Standalone email-safe digest — no base.html inheritance |

---

## BRAND & DESIGN SYSTEM

### Visual Aesthetic
Cool, maritime, professional. Dark navy headers and navigation; light cool-grey page backgrounds; data presented with monospaced fonts on clean white/foam cards. The feel is a Bloomberg terminal meets a nautical chart — data-dense but legible. Accent colour is a warm coral-orange (`--catch`) used sparingly for CTAs and alerts only.

### Typography
| Role | Font | Weight | Usage |
|---|---|---|---|
| Display/headings | Playfair Display (serif) | 400–700 | H1–H3, section titles, hero text |
| Body | IBM Plex Sans | 400–600 | Body copy, labels, nav, UI text |
| Data/mono | IBM Plex Mono | 400–500 | Prices, codes, dates, buttons, badges |

### Colour Palette (authoritative — from `tokens.css`)
| Token | Hex | Role |
|---|---|---|
| `--ink` | `#0f1820` | Primary text, dark section backgrounds |
| `--paper` | `#e8ecf0` | Page background (light cool grey) |
| `--tide` | `#1c2b35` | Primary brand — nav, headers, key accents |
| `--salt` | `#d0d8e0` | Secondary backgrounds, progress bar tracks |
| `--catch` | `#c8401a` | CTA buttons, alerts, accent highlights (coral-orange) |
| `--foam` | `#f4f6f8` | Card backgrounds, section fills |
| `--muted` | `#6a7a88` | Secondary text, labels, helper text |
| `--rule` | `#c0cad4` | Borders, dividers, table rules |
| `--up` | `#4aaa6a` | Price increase (green) |
| `--down` | `#c85040` | Price decrease (red) |
| `--ink-body` | `#3a4a58` | Body text on light backgrounds |
| `--ink-deep` | `#2a3a48` | Footer text, secondary dark elements |
| `--tide-light` | `#7ab0c8` | Text/icons on dark teal backgrounds |
| `--zone-nav` | `#1c2b35` | Navigation bar background |
| `--zone-deep` | `#0f1820` | Ticker bar, card footers, deepest zones |
| `--zone-mid` | `#162028` | Mid-tone dark zones |
| `--zone-strip` | `#141e24` | Stat strip background |

**Important:** BRAND.md documents the original warm palette — ignore it for hex values. `tokens.css` is authoritative.

### Component Styles
- **Buttons:** IBM Plex Mono, uppercase, 0.08em letter-spacing, border-radius ≤2px, `--catch` fill for primary, `--tide` outline for secondary
- **Cards:** `--foam` background, 1px `--rule` border, border-radius 2px, subtle box-shadow
- **Tables:** `--paper` background, `--rule` borders, alternating `--foam` rows, mono font for price data
- **Nav:** `--zone-nav` background, `--tide-light` links, `--catch` active indicator
- **Ticker:** `--zone-deep` background, `--tide-light` text, continuous CSS scroll animation
- **Stat strip:** `--zone-strip` background, white headings, `--tide-light` values

### Spacing
- Base unit: 4px (0.25rem)
- Common values: 4, 8, 12, 16, 24, 32, 48, 64, 96px
- Section padding: 48–96px vertical
- Card padding: 16–24px

---

## USER FLOW (COMPLETE)

### 1. Port Operator — Email Upload (HITL)

```
Port emails price sheet to prices@quayside.fish
  → ingest.py polls IMAP (every N min)
  → attachment identified by port slug in sender or subject
  → extractors/ dispatch: XLS → xls.py, PDF → pdf.py, image → image.py, unknown → ai.py
  → PriceRecord list returned
  → upload record created in DB (status: pending)
  → confirmation email sent with /confirm/<token> link
Reviewer visits /confirm/<token>
  → sees extracted table
  → clicks "Approve" → records upsert into prices table (INSERT OR REPLACE)
  → OR clicks "Edit" → edits rows → approves
  → OR upload auto-published after 2h (confirm.auto_publish_stale_uploads)
```

### 2. Port Operator — Web Upload

```
/port/<slug>/upload → file drag-drop or form entry
  → POST → extractors/ → upload record
  → redirects to /confirm/<token>
  → same approval flow as email ingestion
```

### 3. Port Operator — New User Onboarding

```
/port/<slug>/onboarding → welcome screens
  → guided tour of dashboard features (how-to drawer)
  → POST /port/<slug>/onboarding/complete → session flag set
  → redirects to /port/<slug> (dashboard)
```

### 4. Scraper Pipeline

```
python -m quayside (or systemd timer every 10 min weekdays)
  → run.py orchestrator
  → _run_scraper() for each active port:
      swfpa.py → Peterhead XLS prices
      brixham.py → Brixham PDF prices
      newlyn.py → Newlyn PDF (+ CFPO fallback)
      scrabster.py → Scrabster HTML table
      lerwick.py → Lerwick XLSX
  → results upserted into prices table
  → CSVs exported to output/
  → quality.py runs 11 checks → issues stored in quality_log
  → report.py generates digest.html
  → email.py sends digest (if SMTP configured)
  → log_scrape_attempt() records outcomes in scrape_log
```

### 5. Trade Subscriber — Daily Usage

```
/trade or /trade/<date>
  → token check (£95/month gating)
  → trade.py queries cross-port species matrix
  → user filters by species category (sidebar)
  → stars species/ports to watchlist
  → sees widest spread opportunities (volume-weighted, min 2 grades)
  → asks AI chat questions about prices
  → downloads CSV export
```

### 6. Ops Monitoring

```
/ops → scrape log status, pipeline health, upload queue
  → /ops/run-pipeline → triggers pipeline (5-min timeout)
  → /ops/quality-report → quality issue list
  → /ops/errors → error dashboard with one-click fixes
  → /ops/errors/fix/<id> → auto-fix applied (e.g., flag outlier, clear stale record)
```

---

## DATA MODEL

### Tables in `data/quayside.db`

**`prices`** — Real port price records (demo excluded)
- `date` TEXT (YYYY-MM-DD)
- `port` TEXT (slug, e.g. "peterhead")
- `species` TEXT (raw scraped name, e.g. "Monks")
- `grade` TEXT (port-specific grade system)
- `price_low`, `price_high`, `price_avg` REAL (£/kg)
- `weight_kg`, `boxes` REAL
- `defra_code` TEXT
- `week_avg` REAL
- `size_band` TEXT
- `upload_id` INTEGER (FK to uploads, if via HITL)
- `flagged` INTEGER (0/1, quality flag)
- UNIQUE(date, port, species, grade) — INSERT OR REPLACE upsert

**`demo_prices`** — Identical schema to prices; stores Demo Port synthetic data separately. Never queried alongside prices.

**`landings`** — Vessel landing records
- `date` TEXT, `port` TEXT, `vessel_name` TEXT, `vessel_code` TEXT
- `species` TEXT, `boxes` INTEGER, `boxes_msc` INTEGER
- UNIQUE(date, port, vessel_name, vessel_code, species)

**`ports`** — Port registry
- `slug` TEXT PK (e.g. "peterhead")
- `name`, `code`, `region`, `data_method`, `status` TEXT
- `data_method`: "scraper" | "upload" | "demo"
- `status`: "active" | "outreach" | "future"
- Seeded on startup by `ports.py`

**`uploads`** — HITL upload records
- `id`, `port_slug`, `filename`, `status` (pending/approved/rejected)
- `created_at`, `token` (confirmation link token)
- `extracted_data` JSON blob of extracted PriceRecords

**`extraction_corrections`** — Corrections applied during AI extraction review

**`scrape_log`** — Per-port scrape attempt log
- `port`, `timestamp`, `success` (0/1), `records_count`, `error_message`

**`quality_log`** — Quality check issues
- `check_name`, `port`, `date`, `severity`, `message`, `resolved` (0/1)
- Unique index prevents duplicates

**`error_log`** — Errors surfaced on `/ops/errors`
- `id`, `port`, `check_name`, `message`, `severity`, `created_at`, `auto_fixable`

**`users`** — User accounts
- `id`, `email`, `password_hash` (bcrypt)
- `role`: "TRADE" | "PORT_OPERATOR" | "ADMIN"

---

## BUSINESS LOGIC

### Species Normalisation (`species.py`)
- Raw names stored exactly as scraped from source (e.g. "Monks", "Cod Lg", "HADDOCK-M")
- `get_canonical_name(raw)` maps via `_CANONICAL_MAP` dict to standard names (e.g. "Monks" → "Monkfish")
- `get_category(canonical)` returns "demersal" | "pelagic" | "shellfish" | "other"
- `is_noisy_species(raw)` filters byproducts, offal, damaged fish, Brixham concatenated suffixes
- Add new mappings to `_CANONICAL_MAP` when adding new ports

### Demo Port Isolation (HARD RULE)
- Demo Port (slug='demo', method='demo') stores data in `demo_prices` — never in `prices`
- `get_all_prices_for_date()` only queries `prices` — demo excluded automatically
- All port list queries must filter: `p.get("data_method") != "demo"`
- Templates use `slug != 'demo'` as belt-and-braces check
- Demo must NEVER appear in digests, trade data, quality checks, port comparisons, about page, or market averages

### Grade Systems (differ by port)
- Peterhead: A1–A5 (A1 = best)
- Brixham: 1–10 (1 = best)
- Newlyn: (1)–(15) in parentheses
- Lerwick: named grades
- Scrabster: no grade system
- Raw grade stored in DB as-is; display normalisation in templates

### Quality Checks (`quality.py` — 11 checks)
1. Outlier prices (MAD — median absolute deviation)
2. Low record counts (fewer species than expected for port)
3. Stale data (no new records > N days)
4. Daily average spikes vs 7-day baseline
5. Seeded/test data detection
6. Live-site smoke test
7. NULL/unknown fields
8. Unmapped species (no canonical mapping)
9. Price sanity (≤0, >£200/kg, low>high)
10. Date sanity (future dates, dates too far in past)
11. Price swings vs 30-day mean (>50% change)

### HITL Confirmation Flow
- Upload record created with `status='pending'` and a unique `token`
- Tokens stored in-memory (lost on restart — HEALTH_AUDIT finding)
- Auto-published after 2 hours by `confirm.auto_publish_stale_uploads()`
- On approval: `INSERT OR REPLACE` into prices table

### Scraper Pattern
```python
def scrape_prices() -> list[PriceRecord]:
    # fetch source URL, parse content, return dataclasses
    return [PriceRecord(date=..., port=..., species=..., ...), ...]
```
Each scraper wrapped in `_run_scraper()` — exceptions caught, returns `(results, error_info)`. One failing port doesn't kill the pipeline.

### Widest Spread Metric (Trade)
- Volume-weighted average price per species across ports
- Minimum 2 grades required (filters thin/illiquid markets)
- Spread = max port avg minus min port avg for that species/date

### Data Processing Engine (`helpers.py` — key functions)
- `build_today_data(port, date)` — prices table + formatting
- `build_trend_data(port, species_list)` — 30-day sparkline data
- `build_insights(port, date)` — outlier detection, missing species, notable changes
- `build_category_stats(port, date)` — demersal/pelagic/shellfish aggregates
- `build_competitive_market(port, date)` — port rank vs network avg
- `build_smart_alerts(port)` — quality-driven contextual alerts
- `build_stat_strip_data()` — 4 KPIs for base.html stat strip

---

## CURRENT STATE

### Working
- Scraper pipeline for 5 active ports (Peterhead, Brixham, Newlyn, Lerwick, Scrabster)
- Port dashboards with full data (prices, trends, insights, competitive positioning)
- Trade intelligence dashboard with species matrix
- HITL upload workflow (email + web)
- Daily/weekly/monthly digest generation and email delivery
- Quality check system with 11 checks
- Error dashboard with auto-fix actions
- Onboarding flow for new port operators
- Immersive dashboard mode with sidebar nav and simplified top bar
- GitHub Actions CI/CD auto-deploy on push to main

### In Progress / Known Issues (from HEALTH_AUDIT.md, 2026-03-20)
| Priority | Issue | Effort |
|---|---|---|
| Critical | Ops dashboard completely unauthenticated — anyone can trigger pipelines | Small |
| High | HITL data upserted to prices BEFORE confirmation (approval is cosmetic) | Large |
| High | `INSERT OR REPLACE` with no pre-storage validation — bad scrapes overwrite good data | Small |
| High | Flask SECRET_KEY falls back to hardcoded "dev-secret-change-me" if env var unset | Small |
| High | API ingest endpoint open if QUAYSIDE_API_KEY env var unset | Small |
| High | In-memory confirmation tokens lost on every deploy/restart | Medium |
| High | No SQLite busy_timeout — concurrent DB access fails instantly | Small |
| High | N+1 query pattern in build_insights() — up to 40 DB queries per page load | Medium |
| Medium | ~60 hardcoded warm-palette hex values in templates (post-migration remnants) | Medium |
| Medium | Border-radius violations — brand rule max 2px, templates use 3–12px | Medium |

### Not Started
- Auth on ops dashboard
- Persistent confirmation tokens (move to DB)
- SQLite connection pooling / busy_timeout
- Test coverage beyond SWFPA scraper (5 tests)

### Recent Git History (last 15 commits)
<!-- git-log-start -->
1. `1682d7c` test: verify SKIP_CONTEXT bypass
2. `05352d7` test: verify pre-commit hook fires
3. `adef534` Immersive dashboard nav: simplified top bar + sidebar cleanup
4. `669fde8` Port onboarding: welcome screens, guided dashboard tour, how-to drawer
5. `30f0799` Widest spread: volume-weighted avg + min 2 grades, dashboard info-tips, ops polish
<!-- git-log-end -->

---

## PORT REGISTRY

16 total ports. Seeded on startup by `ports.py`.

| Slug | Name | Code | Region | Method | Status |
|---|---|---|---|---|---|
| demo | Demo Port | DEM | Scotland — North East | demo | active |
| peterhead | Peterhead | PTH | Scotland — North East | scraper | active |
| lerwick | Lerwick | LWK | Scotland — North & Islands | scraper | active |
| scrabster | Scrabster | SCR | Scotland — North & Islands | scraper | active |
| brixham | Brixham | BRX | England — South West | scraper | active |
| newlyn | Newlyn | NLN | England — South West | scraper | active |
| fraserburgh | Fraserburgh | FRB | Scotland — North East | upload | outreach |
| kinlochbervie | Kinlochbervie | KLB | Scotland — North & Islands | upload | outreach |
| macduff | Macduff | MCD | Scotland — North East | upload | outreach |
| eyemouth | Eyemouth | EYE | Scotland — South East | upload | outreach |
| grimsby | Grimsby | GRM | England — East | upload | outreach |
| fleetwood | Fleetwood | FLW | England — North West | upload | outreach |
| lowestoft | Lowestoft | LOW | England — East | upload | future |
| whitby | Whitby | WHT | England — North East | upload | future |
| milford-haven | Milford Haven | MLF | Wales | upload | future |
| kilkeel | Kilkeel | KIL | Northern Ireland | upload | future |

---

## CONTEXT FOR AI

### Key Decisions Made
- **No ORM** — SQLite with parameterised raw SQL for full control and simplicity; no migration overhead
- **Demo port in separate table** — prevents data leakage into real market data; enforced at DB level not just app level
- **Species normalisation at display time** — raw names stored as-is, canonical mapping applied in Python; makes adding new ports easy without backfilling
- **INSERT OR REPLACE strategy** — latest scrape always wins; trades historical accuracy for simplicity
- **In-memory HITL tokens** — simple but breaks on restart; known issue, not yet prioritised
- **Single gunicorn worker** — required for APScheduler to work correctly (no duplicate runs)
- **No ORM migrations** — schema managed manually in `db.py`; `CREATE TABLE IF NOT EXISTS` on startup
- **Cool-neutral theme** — diverged from warm BRAND.md palette; tokens.css is authoritative, BRAND.md is outdated

### Non-Obvious Constraints
- `fraserburgh.py` scraper is dormant — SWFPA stopped publishing Fraserburgh data
- CFPO is a fallback source for Newlyn (used when Newlyn's own PDF isn't available)
- The `week_avg` column in prices is populated by a secondary pass in the pipeline, not by scrapers
- Gunicorn must use `--workers 1` — APScheduler will run N copies of every job otherwise
- ~60 warm-palette hex values are hardcoded in templates that weren't migrated to CSS tokens

### Coding Conventions
- Scrapers return `list[PriceRecord]` or `list[LandingRecord]` — no raw dicts
- All DB queries are parameterised (no string concatenation with user input)
- Blueprint files contain only route handlers; business logic lives in `helpers.py` and module files
- Template partials use underscore prefix (`_chat_float.html`, `_howto_drawer.html`, `_nav_dashboard.html`)
- Demo port exclusion required in EVERY new feature that lists ports or queries market data
- Dates always ISO 8601 (YYYY-MM-DD) in DB and filenames

### Development Server
```bash
python -m quayside.web.app   # Flask at http://localhost:5000
```

### Pre-commit Hook
`scripts/generate_context.py` updates `(NNN lines)` annotations and git log in this file automatically.
Bypass with: `SKIP_CONTEXT=1 git commit`

---

*Auto-generated by /claudeupdate in Claude Code.*
