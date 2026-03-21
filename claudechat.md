# Quayside — Full Project Context

## IDENTITY

- **Name:** Quayside
- **Type:** B2B data product — UK fish auction price aggregator and market intelligence platform
- **Stack:** Python 3.9+ / Flask / SQLite / Jinja2 / Claude API
- **Status:** Live in production at https://quaysidedata.duckdns.org/
- **Purpose:** Scrapes daily fish auction prices from 5 UK ports, normalizes them into a single database, and serves a web dashboard + daily digest for fish merchants, port operators, and traders. Also supports manual price uploads from ports that can't be scraped.
- **Repo:** github.com/neilhenrypeacock/quayside (private)

---

## FULL TECH STACK

| Layer | Technology | Version |
|---|---|---|
| Language | Python | 3.9+ |
| Web framework | Flask | 3.0+ |
| Database | SQLite (WAL mode) | System |
| Templating | Jinja2 | 3.1+ |
| Auth | Flask-Login | 0.6+ |
| Scheduling | APScheduler | 3.10+ |
| AI extraction | Anthropic Claude API (Sonnet for extraction, Haiku for chatbot) | anthropic >= 0.39 |
| PDF parsing | pdfplumber | 0.11+ |
| XLS parsing | xlrd (XLS), openpyxl (XLSX) | xlrd >= 2.0, openpyxl >= 3.1 |
| HTML scraping | BeautifulSoup4 + lxml | bs4 >= 4.11, lxml >= 4.9 |
| HTTP | requests | 2.28+ |
| WSGI server | gunicorn | 22.0+ |
| Reverse proxy | nginx | System |
| Process manager | systemd | System |
| CI/CD | GitHub Actions (SSH deploy) | — |
| Linting | Ruff | 0.4+ |
| Testing | pytest | 7.0+ |
| Hosting | Hetzner Cloud VPS | Debian/Ubuntu |
| Fonts | Google Fonts (Playfair Display, IBM Plex Sans, IBM Plex Mono) | CDN |

---

## FILE STRUCTURE

```
quayside/
├── CLAUDE.md                     # Project instructions for Claude Code
├── BRAND.md                      # Brand kit (colours, typography, components)
├── PORTS.md                      # UK & Ireland fish port audit (30 ports, data sources)
├── ROADMAP.md                    # Development phases and status
├── pyproject.toml                # Python package config, dependencies, ruff/pytest settings
├── Dockerfile                    # Container build (Python 3.11-slim, gunicorn)
├── Procfile                      # Heroku/Railway process definition
├── railway.toml                  # Railway.app deployment config
├── deploy/
│   ├── update.sh                 # Server-side deploy script (git pull, pip install, restart)
│   ├── setup.sh                  # First-time server setup (nginx, certbot, user creation)
│   ├── run_pipeline.sh           # Smart pipeline scheduler (weekday/hour logic, ETag checks)
│   ├── quayside-nginx.conf       # nginx reverse proxy config
│   ├── quayside.service          # systemd service for gunicorn web app
│   ├── quayside-pipeline.service # systemd one-shot for pipeline runs
│   ├── quayside-pipeline.timer   # Every 10 min, weekdays
│   ├── quayside-quality.service  # systemd one-shot for quality checks
│   ├── quayside-quality.timer    # 3× daily (10:00, 13:00, 16:00)
│   └── authorized_keys           # SSH public keys for deployment
├── .github/workflows/
│   └── deploy.yml                # GitHub Actions: SSH to server on push to main
├── src/quayside/
│   ├── __init__.py
│   ├── __main__.py               # CLI entry point (--update flag for ETag mode)
│   ├── run.py                    # Pipeline orchestrator (519 lines)
│   ├── db.py                     # SQLite schema + queries (1424 lines)
│   ├── models.py                 # PriceRecord + LandingRecord dataclasses (32 lines)
│   ├── species.py                # Species normalisation + noise filter (313 lines)
│   ├── ports.py                  # Port registry — 16 ports (76 lines)
│   ├── report.py                 # Daily HTML digest builder (762 lines)
│   ├── review.py                 # Weekly/monthly review builder + sparklines (504 lines)
│   ├── trade.py                  # Trade dashboard data builder (907 lines)
│   ├── quality.py                # 11 data-quality checks (1104 lines)
│   ├── error_actions.py          # Error fix actions + plain-English explanations (289 lines)
│   ├── export.py                 # Per-port CSV export (33 lines)
│   ├── email.py                  # SMTP digest delivery (83 lines)
│   ├── confirm.py                # HITL upload confirmation (190 lines)
│   ├── ingest.py                 # IMAP email ingestion (225 lines)
│   ├── scheduler.py              # APScheduler background tasks (143 lines)
│   ├── template.py               # XLSX upload template generator (163 lines)
│   ├── http_cache.py             # ETag/content-hash HTTP caching (126 lines)
│   ├── fx.py                     # GBP/EUR FX rate fetcher (70 lines)
│   ├── extractors/
│   │   ├── __init__.py           # Router: file extension → extractor (0 lines)
│   │   ├── ai.py                 # Claude API fallback extractor (130 lines)
│   │   ├── csv_ext.py            # CSV extractor with auto-dialect (87 lines)
│   │   ├── image.py              # Image extractor via Claude Vision (117 lines)
│   │   ├── pdf.py                # PDF table extractor + AI fallback (97 lines)
│   │   └── xls.py                # XLS/XLSX extractor + AI fallback (165 lines)
│   ├── scrapers/
│   │   ├── swfpa.py              # SWFPA event discovery + Peterhead XLS (256 lines)
│   │   ├── brixham.py            # Brixham PDF prices (174 lines)
│   │   ├── newlyn.py             # Newlyn PDF prices (201 lines)
│   │   ├── scrabster.py          # Scrabster HTML table prices (147 lines)
│   │   ├── lerwick.py            # Lerwick XLSX prices (179 lines)
│   │   ├── cfpo.py               # CFPO PDF Newlyn backup (77 lines)
│   │   └── fraserburgh.py        # Fraserburgh HTML prices — dormant (161 lines)
│   ├── templates/
│   │   └── digest.html           # Email-safe digest template (1437 lines)
│   └── web/
│       ├── app.py                # Flask factory, CSRF, security, blueprints (172 lines)
│       ├── auth.py               # Login/register/logout blueprint (122 lines)
│       ├── public.py             # Public marketing pages blueprint (117 lines)
│       ├── port_views.py         # Port dashboard + upload blueprint (865 lines)
│       ├── trade_views.py        # Trade dashboard blueprint (310 lines)
│       ├── ops_views.py          # Ops + quality + errors blueprint (873 lines)
│       ├── api_views.py          # REST API blueprint (198 lines)
│       ├── digest.py             # Digest serving blueprint (86 lines)
│       ├── helpers.py            # Data processing engine (1474 lines)
│       ├── static/
│       │   ├── css/tokens.css    # Design tokens + component CSS (1089 lines)
│       │   └── img/              # 3 marketing images
│       └── templates/            # 27 Jinja2 templates (~18,800 lines)
├── tests/
│   ├── test_swfpa.py             # 6 tests for Peterhead XLS parser
│   └── fixtures/
│       └── peterhead_prices_sample.xls
├── scripts/
│   ├── backfill_peterhead.py     # Historical data backfill
│   └── run_if_needed.sh          # Wrapper script
├── data/                         # (gitignored) SQLite DB + uploads
└── output/                       # (gitignored) CSVs + digest HTML
```

**Total:** ~12,800 lines of Python, ~18,800 lines of Jinja2/HTML, ~1,070 lines of CSS.

---

## SCREENS & PAGES (exhaustive)

### 1. Landing Page (`/`)
**Template:** `landing.html` (1494 lines) | **Blueprint:** `public`

**Layout:** Full-width marketing page with editorial newspaper aesthetic. Sections:
- **Ticker strip:** Scrolling price ticker across top (key species × ports, color-coded up/down arrows)
- **Stat strip:** 4 KPIs — ports live today, species tracked, price records, widest spread
- **Hero section:** "Today at a Glance" — Haddock prices per port with day-over-day %, top movers, FX rate
- **Key species movers:** Best prices for high-value species with weight thresholds (>25kg)
- **Email digest mock:** Preview of what daily email digest looks like
- **How it works:** 3-step explanation
- **Pricing plans:** Free, Pro (£95/mo), Custom — with feature comparison
- **Port index:** List of all active + outreach ports with status indicators
- **Waitlist CTA:** Email signup for launch waitlist

**Data sources:** `report.build_landing_data()`, ticker from context processor `inject_ticker()`

### 2. Overview Hub (`/overview`)
**Template:** `index.html` (244 lines) | **Blueprint:** `public`

**Layout:** Card grid showing all screens/pages as navigation cards. Each card shows port name, freshness status (live/stale/offline), and link to dashboard.

**Data:** Lists active ports with real-time freshness detection (compares latest data date vs today).

### 3. For Ports (`/for-ports`)
**Template:** `for_ports.html` (867 lines) | **Blueprint:** `public`

**Layout:** Marketing page targeting port operators. Sections: hero, benefits grid, upload workflow explanation, template download CTA, email digest mockup, signup form.

### 4. For Traders (`/for-traders`)
**Template:** `for_traders.html` (2022 lines) | **Blueprint:** `public`

**Layout:** Marketing page for fish merchants. Features: cross-port price comparison demo, trade dashboard preview, pricing plans, FAQ section. Heavy on feature descriptions and use cases.

### 5. About (`/about`)
**Template:** `about.html` (722 lines) | **Blueprint:** `public`

**Layout:** 3-tier explanation (simple → detailed → technical), port coverage table listing all active ports with region and data method. Demo port explicitly excluded.

### 6. Methodology (`/methodology`)
**Template:** `methodology.html` (179 lines) | **Blueprint:** `public`

**Layout:** Documentation page explaining data collection methods, species normalisation, grade systems, quality checks.

### 7. Login (`/login`)
**Template:** `login.html` (208 lines) | **Blueprint:** `auth`

**Layout:** Email/password form with role indicator. Post-login routing: port operators → their port dashboard, admins → ops, traders → trade dashboard.

### 8. Register (`/register`)
**Template:** `register.html` (214 lines) | **Blueprint:** `auth`

**Layout:** Registration form with email, password (8+ chars), role selection (TRADE, PORT_OPERATOR, ADMIN), port selector for port operators. Demo port excluded from port list.

### 9. Port Dashboard (`/port/<slug>`)
**Template:** `dashboard.html` (3597 lines) | **Blueprint:** `port`

**Layout:** The most complex page. Sections:
- **Port header:** Port name, status indicator (live/stale/offline), freshness tag
- **Freshness banner:** Shown when displaying previous day's data
- **Welcome banner:** First-visit helper text
- **Hero stats:** 4 KPIs — avg price today, vs market %, vs last week %, vs 30-day avg %
- **Smart alert cards:** 3-4 actionable alerts (price spikes, spread opportunities, supply changes, calm market)
- **Date selector:** Navigate between trading dates
- **Price table:** Full species × grade table with prices, market comparison, volume, day-over-day %
- **Competitive position:** Toggle-able section showing this port vs market for each species (bar charts)
- **Best performers:** Top 3 species by 30-day price change
- **Category breakdown:** Demersal, flatfish, shellfish, pelagic groupings with stats
- **Trend chart:** 90-day price history (inline SVG sparklines)
- **Insights:** Plain-English market commentary
- **Floating chat FAB:** AI chatbot (Claude Haiku) with suggested prompts

**Data sources:** `helpers.build_today_data()`, `helpers.build_trend_data()`, `helpers.build_insights()`, `helpers.build_category_stats()`, `helpers.build_competitive_market()`, `helpers.build_smart_alerts()`, `helpers.build_best_performers()`

**Special handling:** Demo port gets synthetic competitive data injected; date navigation uses AJAX via prices partial.

### 10. Prices Partial (`/port/<slug>/prices`)
**Template:** `prices_partial.html` (151 lines) | **Blueprint:** `port`

**Layout:** Just the prices table — served via AJAX for date switching without full page reload.

### 11. Upload Form (`/port/<slug>/upload`)
**Template:** `upload_form.html` (166 lines) | **Blueprint:** `port`

**Layout:** Two upload methods: file upload (drag-and-drop, accepts XLS/XLSX/CSV/PDF/images) or inline form entry (species/grade/price fields). Template download button.

### 12. Confirmation Page (`/confirm/<token>`)
**Template:** `confirm.html` (94 lines) | **Blueprint:** `port`

**Layout:** Review table showing extracted prices. Two buttons: "Looks Good" (approve) or "Fix Something" (edit). Auto-publish warning.

### 13. Edit Page (`/confirm/<token>/edit`)
**Template:** `edit.html` (98 lines) | **Blueprint:** `port`

**Layout:** Editable table of extracted prices. Each row has species/grade/price inputs. Save applies corrections and auto-confirms.

### 14. Submit/Signup (`/port/submit` or `/port/<slug>/submit`)
**Template:** `submit.html` (474 lines) | **Blueprint:** `port`

**Layout:** Contact/signup form for ports to express interest. Pre-selects port if slug provided. No auth required.

### 15. Daily Digest (`/digest` or `/digest/<date>`)
**Template:** `digest_wrapper.html` (131 lines) wrapping `digest.html` (1437 lines) | **Blueprint:** `digest`

**Layout:** Email-safe HTML report showing:
- Header ticker (top price from each port)
- Alert band (port count + species count)
- Price table (all species × all ports, grouped by species, best-price markers)
- Cross-port comparison bars (species at 2+ ports with visual bars and 30-day avg markers)
- Benchmark snapshot (10 key commercial species)
- Market summary (risers, fallers)

Uses Georgia/Courier email-safe fonts. Self-contained HTML (no external CSS).

### 16. Weekly Report (`/digest/weekly`)
**Template:** `weekly.html` (486 lines) | **Blueprint:** `digest`

**Layout:** 7-calendar-day review with:
- Summary stats (reporting days, species count, market direction)
- Top risers and fallers with sparkline SVGs
- Benchmark heatmap (species × dates, color-coded)
- Value ranking (best-price ports per species)
- Price spreads table

**Data source:** `review.build_weekly_data()`

### 17. Monthly Report (`/digest/monthly`)
**Template:** `monthly.html` (513 lines) | **Blueprint:** `digest`

**Layout:** Month-long review with:
- Summary (market direction, trading days, species)
- Trend charts with datasets per port
- Volatility ranking (standard deviation)
- Reliability scores (port completeness %)
- Availability matrix (species × ports)
- Month-over-month comparison

**Data source:** `review.build_monthly_data()`

### 18. Trade Dashboard (`/trade` or `/trade/<date>`)
**Template:** `trade.html` (3420 lines) | **Blueprint:** `trade`

**Layout:** Premium species-first cross-port intelligence. Sections:
- **Market pulse:** Today at a Glance KPIs — ports reporting, species tracked, market direction %, best value port
- **Smart alerts:** 3-4 alert cards (same pattern as port dashboard)
- **Watchlist cards:** Full-width rows for each species showing:
  - Species name (serif italic) + category badge
  - Price changes (vs yesterday, vs 7d, vs 30d)
  - Grid of ports with prices, grades, volumes
  - Footer with market avg, best buy indicator
- **Opportunity rows:** Top arbitrage opportunities (cross-port spread)
- **Deep dive section:** Click-to-expand per-species detail with KPIs, port grid, trend data
- **Sidebar navigation:** Tab-based scroll navigation
- **Floating chat FAB:** Shared AI chatbot partial

**Data source:** `trade.build_trade_data()` — returns matrix, highlights, momentum, arbitrage, pulse

**Access control:** Token-gated via `TRADE_TOKEN` env var (cookie-based).

### 19. Trade Gate (`/trade` when no access)
**Template:** `trade_gate.html` (25 lines) | **Blueprint:** `trade`

**Layout:** Paywall page showing £95/month pricing, feature list, signup CTA.

### 20. Port Directory (`/trade/ports`)
**Template:** `trade_ports.html` (314 lines) | **Blueprint:** `trade`

**Layout:** Contact directory with auction times, phone numbers, websites for each active + outreach port. Hardcoded port contact info.

### 21. Ops Dashboard (`/ops`)
**Template:** `ops.html` (1104 lines) | **Blueprint:** `ops`

**Layout:** Internal operations dashboard (no auth required). Sections:
- **Port status by region:** Coverage heatmap (last 3 weeks × active ports)
- **Scrape alerts:** Missing data for expected auction days with reasoning
- **Per-port metrics:** First data, success days, fail count, records, 30-day value
- **Day-of-week frequency:** Last 90 days detection (Mon-Fri, 3×/week, etc.)
- **Today's scrape timeline:** Success/fail by 30-min slots (7am–5pm)
- **Upload queue:** Pending/confirmed/published counts
- **Quality issues:** Last 7 days by severity

### 22. Quality Report (`/ops/quality-report`)
**Template:** `quality_report.html` (592 lines) | **Blueprint:** `ops`

**Layout:** Comprehensive quality report with port-by-port dashboards, digest preview, ops health summary. Download as markdown option.

### 23. Error Dashboard (`/ops/errors`)
**Template:** `errors.html` (546 lines) | **Blueprint:** `ops`

**Layout:** Quality check errors with:
- Plain-English explanations for each error type
- One-click fix actions (flag record, flag port day, mark thin data)
- Scan now button, fix all button
- Download report as markdown
- Next scheduled scan time

**Data source:** `error_actions.py` for explanations and fix logic.

### 24. Chat Partial (`_chat_float.html`)
**Template:** `_chat_float.html` (126 lines) | Shared partial

**Layout:** Floating action button (FAB) in bottom-right corner. Expands to chat panel with:
- Suggested prompt pills
- Message history (user/assistant bubbles)
- Input row with send button
- Mobile-responsive (full-width on small screens)

Used by both port dashboard and trade dashboard.

---

## COMPONENT INVENTORY (exhaustive)

All components are CSS-only (no JavaScript framework). Defined in `tokens.css` (1089 lines).

### Navigation
- **Nav bar:** Sticky top bar, dark background (`--zone-nav`), logo left, links right, burger menu on mobile
- **Nav dropdown:** Click/hover dropdowns with caret animation, menu items with hover states
- **Sign In button:** Outlined button with catch color, hover fills
- **Mobile nav:** Burger menu → full-width dropdown on ≤768px

### Data Display
- **Ticker strip:** Scrolling CSS animation (40s linear infinite), duplicated items for seamless loop, port codes in muted, prices color-coded up/down
- **Stat strip:** 4 flex items with labels (8px mono uppercase), values (18px mono), sub-text, dividers
- **Price table:** Monospace prices right-aligned, 2px border-bottom on headers, sorted borders
- **Market bars:** 8px height bar track with fill + absolute-positioned marker for port's position
- **Watchlist cards:** Full-width species cards with header (species name + category badge + change indicators), port cell grid (1px gap dividers), dark footer with market summary
- **Alert cards:** Flex row of colored left-border cards (spike=tide, spread=amber, opportunity=green, supply=catch, calm=rule)
- **Opportunity rows:** Monospace list items with species (serif italic) and data columns
- **Deep dive KPIs:** Auto-fill grid of small metric cards

### Interactive
- **Floating chat FAB:** Fixed position bottom-right, 56px circular button, expands to 360px panel with message bubbles, input row, pill suggestions
- **Date selector:** Standard form controls styled with brand tokens

### Layout
- **Cards:** White background, 1px rule border, 3px tide top border, 2px radius
- **Section labels:** 8px mono uppercase with extending rule line via `::after`
- **Page header:** Bottom heavy rule (3px tide) + 1px rule line

### Status Indicators
- **Status dots:** 8px circles — confirmed (green), pending (amber), stale (amber), offline (red), none (grey)
- **Badges:** Mono 8px uppercase, 2px radius — best (tide bg), below (catch outline)
- **Grade badges:** Salt background, mono 9px, rule border
- **Freshness tags:** Colored backgrounds — live (green tint), recent (amber tint), stale (red tint)

### Forms
- **Inputs:** 1px rule border, 2px radius, focuses to tide border
- **Buttons:** Primary (catch bg, white text), secondary (foam bg, tide text, rule border), ghost (underline only), danger (catch bg)
- **Flash messages:** Foam bg, 3px tide left border

---

## BRAND & DESIGN SYSTEM (exhaustive)

### Overall Aesthetic
Cool-neutral editorial/newspaper design. Sharp edges (2px max radius). Borders instead of shadows. Monospace labels. Data-forward. No visual clutter.

### Colour Palette (from live `tokens.css`)

| Token | Hex | Role |
|---|---|---|
| `--ink` | `#0f1820` | Primary text colour, dark section backgrounds |
| `--paper` | `#e8ecf0` | Page background — cool light grey |
| `--tide` | `#1c2b35` | Brand primary — nav, headers, card top borders, accents |
| `--salt` | `#d0d8e0` | Secondary backgrounds, bar tracks, table alternates |
| `--catch` | `#c8401a` | CTA buttons, alerts, logo "side" text, accent pops |
| `--foam` | `#f4f6f8` | Card backgrounds, section fills, input backgrounds |
| `--muted` | `#6a7a88` | Secondary text, labels, placeholder text |
| `--rule` | `#c0cad4` | Borders, dividers, table lines |
| `--up` | `#4aaa6a` | Price increase indicators, positive change |
| `--down` | `#c85040` | Price decrease indicators, negative change |
| `--ink-body` | `#3a4a58` | Body text on light backgrounds (softer than ink) |
| `--tide-light` | `#7ab0c8` | Light teal for text on dark/teal backgrounds |
| `--ink-deep` | `#2a3a48` | Very dark slate — footer, secondary dark text |
| `--zone-nav` | `#1c2b35` | Navigation bar background |
| `--zone-deep` | `#0f1820` | Ticker, card footers, deep sections |
| `--zone-mid` | `#162028` | Dropdown menu backgrounds |
| `--zone-strip` | `#141e24` | Stat strip background |

**Additional hardcoded colours in tokens.css:**
- Nav link text: `#5a7a8a` (light slate on dark bg)
- Nav link hover: `#e8eef2` (near-white)
- Nav brand text: `#e8eef2` (near-white, "Quay")
- Ticker text: `#a8c8d8` (light blue-grey)
- Ticker prices: `#d0e8f0` (near-white blue)
- Ticker label: `#3a6a7a` (muted teal)
- Stat strip labels: `#2a4a5a` (very muted teal)
- Stat strip values: `#c8d8e0` (light blue-grey)
- Stat strip dividers: `#1e2e38` (very dark teal)
- Badge text: `#5a5040` (warm dark, legacy)
- Pending/opportunity warn: `#c8941a` (amber)
- Freshness live: `#3a7a5a` (dark green)
- Freshness recent: `#8a7a3a` (dark amber)

### Typography

| Role | Font Family | Weights | Sizes | Usage |
|---|---|---|---|---|
| Headings | Playfair Display | 400, 700, 900 + italic | 18-28px | Page titles, section headings, species names in tables (italic) |
| Body | IBM Plex Sans | 300, 400, 500 | 13-14px default | Body copy, descriptions, form labels, chat messages |
| Data/Labels | IBM Plex Mono | 400, 500 | 7-12px | Prices, port codes, section labels (8-10px), badges (7-9px), buttons (11px), nav links (11px), stat values (18px) |

**Google Fonts import:**
```html
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap" rel="stylesheet">
```

**Email fallbacks:** Georgia (headings), system sans-serif (body), Courier New (data).

### Spacing
- Container: `max-width: 960px`, `padding: 24px 32px`
- Nav: `padding: 16px 32px`
- Cards: `padding: 24px` (main), `padding: 16px 18px` (alerts), `padding: 14px 16px` (KPIs)
- Tables: `padding: 8px` (cells)
- Ticker: `padding: 8px 0`, items spaced `40px`
- Section labels: `margin-bottom: 10px`, `gap: 10px`
- Stat strip: `padding: 10px 20px`, items: `padding: 0 20px`

### Border & Radius
- **Maximum radius:** 2px (enforced everywhere)
- **Card border:** `1px solid var(--rule)` + `border-top: 3px solid var(--tide)`
- **Table header border:** `2px solid var(--tide)`
- **Rule weights:** heavy `3px solid var(--tide)`, light `1px solid var(--rule)`, deep `1px solid #0a1218`
- **No box-shadows** on cards (exception: chat FAB has `box-shadow: 0 4px 16px rgba(0,0,0,0.15)`)

### Button Styles
- **Primary:** `background: var(--catch)`, `color: white`, mono 11px uppercase, `letter-spacing: 0.1em`, `padding: 10px 24px`, hover darkens + translateY(-1px)
- **Secondary:** `background: var(--foam)`, `border: 1px solid var(--rule)`, `color: var(--tide)`, hover to salt
- **Ghost:** No background, `border-bottom: 1px solid var(--rule)`, hover darkens
- **Danger:** Same as primary (catch bg, white text)
- **Sign In:** Outlined `border: 1px solid var(--catch)`, `color: var(--catch)`, hover fills

### Logo
Typographic: `Quay<span>side</span>` — "Quay" in near-white (`#e8eef2` on dark nav), "side" in `--catch` (`#c8401a`). Playfair Display, 20px, weight 700, letter-spacing -0.02em.

---

## USER FLOW (complete)

### Public Visitor Flow
1. Lands on `/` → sees marketing hero, ticker, pricing plans, port index
2. Can browse: `/about`, `/methodology`, `/for-ports`, `/for-traders`
3. Can view yesterday's digest: `/digest/yesterday`
4. Can view overview hub: `/overview` → click any port → port dashboard
5. Can access demo port: `/port/demo` (synthetic data, showcases product)

### Port Operator Flow
1. Discovers product via `/for-ports` or direct outreach
2. Registers at `/register` with PORT_OPERATOR role, selects their port
3. Logs in → redirected to their port dashboard (`/port/<slug>`)
4. Views today's prices, trends, competitive position, insights
5. Uploads prices: `/port/<slug>/upload` → file upload or inline form
6. Reviews extraction: `/confirm/<token>` → approve or edit
7. Downloads template: `/port/<slug>/template` for standardized submissions
8. Exports data: `/port/<slug>/export` (365-day CSV)
9. Uses AI chat for market questions (floating FAB)

### Fish Trader Flow
1. Discovers product via `/for-traders`
2. Registers at `/register` with TRADE role
3. Accesses trade dashboard: `/trade` (token-gated, or `/trade/<date>`)
4. Views species × port matrix, watchlist cards, arbitrage opportunities
5. Filters by port selection (`?ports=Peterhead,Brixham`)
6. Uses deep dive for per-species detail
7. Exports data: `/trade/export` (CSV, 90-day default)
8. Views port directory: `/trade/ports` (auction times, contacts)
9. Provides feedback: `/trade/feedback`
10. Uses AI chat for market questions

### Email Upload Flow (automated)
1. Port sends price sheet (XLS/CSV/PDF/image) to ingest mailbox
2. `ingest.py` polls IMAP, identifies port by sender email
3. Attachment saved to `data/uploads/{port_slug}/{date}/`
4. Extractor parses file → `list[PriceRecord]`
5. Upload record created, confirmation email sent with review link
6. Reviewer approves or edits at `/confirm/<token>`
7. On approval: records upserted into prices table
8. If no action after 2 hours: auto-published

### Pipeline Flow (automated, every 10 min weekdays)
1. `run_pipeline.sh` checks: weekday? within 07:00–17:00?
2. If no digest exists today: full run
3. If data changed recently: ETag update check
4. If >60 min since last attempt: hourly pulse
5. `run.py main()`:
   - SWFPA event discovery (shared — gets Peterhead XLS, Brixham PDF, Newlyn PDF URLs)
   - Runs 5 scrapers in sequence (each wrapped in error handler)
   - Newlyn: tries SWFPA first, falls back to CFPO
   - Upserts prices into SQLite
   - Exports per-port CSVs
   - Processes email uploads
   - Auto-publishes stale uploads
   - Runs quality checks
   - Generates HTML digest
   - Sends email digest (if SMTP configured)
6. Results logged to `scrape_log` table

### Ops Flow (internal)
1. View ops dashboard: `/ops` — scrape health, coverage heatmap, alerts
2. Trigger pipeline manually: POST `/ops/run-pipeline`
3. Trigger quality checks: POST `/ops/run-quality-check`
4. View quality report: `/ops/quality-report`
5. View error dashboard: `/ops/errors` — plain-English explanations, one-click fixes
6. Download reports as markdown

---

## DATA MODEL

### PriceRecord (dataclass)
```python
@dataclass
class PriceRecord:
    date: str          # YYYY-MM-DD
    port: str          # Port name (e.g., "Peterhead")
    species: str       # Raw species name as scraped
    grade: str         # Grade (A1-A5, 1-10, (1)-(15), ALL, etc.)
    price_low: float | None
    price_high: float | None
    price_avg: float | None
    scraped_at: str | None     # ISO timestamp
    weight_kg: float | None    # Volume in kg
    boxes: int | None          # Number of boxes
    defra_code: str | None     # 3-letter DEFRA species code
    week_avg: float | None     # Weekly average
    size_band: str | None      # Size descriptor
```

### LandingRecord (dataclass)
```python
@dataclass
class LandingRecord:
    date: str
    port: str
    vessel_name: str
    vessel_code: str
    species: str
    boxes: int | None
    boxes_msc: int | None      # MSC-certified boxes
    scraped_at: str | None
```

### Species Normalisation
~100 canonical species names in `_CANONICAL_MAP` (species.py). Categories: demersal, flatfish, shellfish, pelagic, other.

10 key species for ticker/benchmarks: Haddock, Cod, Monkfish, Lemon Sole, Plaice, Whiting, Nephrops, Halibut, Turbot, Coley (Saithe).

Cross-port name examples: "Monks" (Peterhead) = "Monkfish" (Scrabster) = "Monk" (Brixham). "Lemons" = "Lemon Sole". "Catfish Scottish" = "Catfish".

### Trade Dashboard Data Shape
`build_trade_data()` returns:
```python
{
    "date": "2026-03-20",
    "matrix": [{
        "species": "Haddock",
        "category": "demersal",
        "ports": {"Peterhead": {"price_avg": 1.45, "grade": "A2", ...}, ...},
        "market_avg": 1.38,
        "vs_30d_pct": 5.2,
        "vs_7d_pct": -1.1,
        "spread_pct": 18.3,
        "best_buy_port": "Brixham",
        "best_buy_price": 1.22,
    }, ...],
    "pulse": {
        "ports_reporting": 4,
        "species_tracked": 45,
        "market_direction_pct": 2.1,
        "best_value_port": "Brixham",
    },
    "arbitrage": [{"species": "Monkfish", "spread_pct": 35, ...}, ...],
    "highlights": {"today": [...], "week": [...], "month": [...], "ytd": [...]},
}
```

---

## BUSINESS LOGIC

### Pipeline Orchestration (`run.py`)
- SWFPA event discovery runs once per pipeline, returns URLs for Peterhead, Brixham, Newlyn
- Each scraper wrapped in `_run_scraper()` — catches all exceptions, returns `(results, error_info)`
- ETag-aware update mode (`--update`): uses `cached_fetch()` to skip unchanged sources
- Newlyn has fallback chain: SWFPA PDF → CFPO PDF

### Quality Checks (`quality.py`, 11 checks)
1. **Outlier price:** >3.5× MAD from 30-day median
2. **Record count:** <40% of rolling median
3. **Stale data:** No new data ≥2/4 trading days
4. **Day avg spike:** Port daily avg ±50%/100% from rolling avg
5. **Seeded data:** Known test timestamps on live ports
6. **Live site smoke test:** Displayed price matches DB
7. **Unknown fields:** NULL/blank/Unknown in port or species
8. **Unmapped species:** No canonical mapping (fuzzy-suggests fix)
9. **Price sanity:** ≤0, >£200/kg, or low > high
10. **Date sanity:** Future-dated or pre-2020 records
11. **Price swing:** >200%/500% vs 30-day mean

### AI Extraction
- **File uploads:** Claude Sonnet extracts structured price data from unknown file formats
- **Image uploads:** Claude Vision API processes photos of price sheets
- **Chatbot:** Claude Haiku (max 400 tokens) for market questions on port/trade dashboards
- Prompts instruct pence-to-pounds conversion, JSON array output format

### Error Actions (`error_actions.py`)
Maps quality check types to fix actions:
- `flag_record`: Sets `flagged=1` on individual price record
- `flag_port_day`: Flags all records for a port on a date
- `mark_thin`: Marks data as thin/unreliable
- `download_only`: No auto-fix available (manual investigation needed)

### Demo Port Isolation
Demo Port (slug='demo') uses `demo_prices` table — completely separate from real `prices` table. Must be excluded from: digests, comparisons, trade dashboard, quality checks, about page, aggregates. Filter with `data_method != "demo"` or `slug != 'demo'`.

---

## CURRENT STATE

### What's Working
- 5 active scrapers (Peterhead, Brixham, Newlyn, Scrabster, Lerwick)
- Full pipeline automation (every 10 min, weekdays, with ETag caching)
- Port dashboards with competitive position, trends, insights, alerts, chat
- Trade dashboard with species × port matrix, watchlist, arbitrage
- Daily/weekly/monthly digest reports
- Upload/HITL workflow (file + form + email ingestion)
- Quality checks (11 checks, auto + scheduled)
- Error dashboard with plain-English explanations + one-click fixes
- Ops dashboard with coverage heatmap, scrape timeline, alerts
- Auto-deploy via GitHub Actions
- Live at https://quaysidedata.duckdns.org/

### In Progress
- Port expansion (6 outreach ports identified)
- Trade dashboard premium features
- Email subscriber delivery

### Not Started
- API subscriptions / tiered pricing
- Custom alerts (price thresholds)
- Buyer system integrations
- Northern Ireland / Ireland port partnerships
- Multi-currency support (FX rate fetcher exists, not integrated)

### Last 15 Git Commits
```
adef534 Immersive dashboard nav: simplified top bar + sidebar cleanup
669fde8 Port onboarding: welcome screens, guided dashboard tour, how-to drawer
30f0799 Widest spread: volume-weighted avg + min 2 grades, dashboard info-tips, ops polish
0bb9ead Deploy: fix diverged-branch failure — use fetch+reset instead of pull --ff-only
2049ebc Nav: simplify menu — rename For Trade, demo port link, remove duplicate digest links, reorder Dev ports
9ca4e03 Demo port: inject synthetic competitive data so dashboard looks complete
c69266c Port dashboard: competitive position toggle, strongest-vs-market reliability filter
34cf10f Ops: fix Today's Pipeline runs column — show first run, first data, last run
807f529 Landing: email digest copy polish, key-species movers, waitlist CTA; dashboard: vs-30d hero stat, market avg column, remove ranking section
e195d97 Port dashboard: merge sections, floating chat FAB, fix price trends accuracy
9bb6b02 Quality check: suppress false-positive record_count errors for today
0ec9a60 Homepage: filter low-volume species from "Best Prices" hero section
48de298 Visual redesign: warm paper palette → cool-neutral theme with stat strip
ec8c5c9 Housekeeping: remove unused imports/variables, fix import sorting, delete stale context doc
7c32e9f Trade dashboard: sidebar tabs, replace inline chat with shared partial
```

---

## OPEN QUESTIONS & ISSUES

### Known Risks
- **Peterhead E-Auction launch (March 31, 2026):** May break the SWFPA XLS format or URL structure
- **SWFPA dependency:** If SWFPA stops publishing files, 3 ports lose data (Peterhead, Brixham, Newlyn)
- **Fraserburgh dormant:** SWFPA stopped publishing Fraserburgh files as of March 2026

### TODOs
- `BRAND.md` documents the original warm paper palette but `tokens.css` has since been updated to a cool-neutral theme — the two are out of sync
- helpers.py at 1475 lines is the largest web module — may benefit from splitting
- Only 6 tests exist (all for SWFPA parser) — test coverage is minimal
- No pagination on any data views
- No rate limiting on API endpoints
- CSRF exempts all `/api/v1/*` routes

### Architecture Notes
- Gunicorn must run with 1 worker to prevent duplicate APScheduler runs
- SQLite WAL mode for read concurrency but single-writer
- All scrapers run sequentially in pipeline (could be parallelized)
- In-memory token store for HITL confirmations (lost on restart)

---

## CONTEXT FOR AI

### Design Decisions
- **SQLite over Postgres:** Chosen for simplicity — single-file DB, no server, easy backup. WAL mode handles read concurrency. Fine for current scale.
- **Flask over Django/FastAPI:** Lightweight, Jinja2 native, blueprint system works well for modular routes.
- **CSS-only components (no JS framework):** Keeps templates simple, email-compatible, fast to iterate.
- **Species normalisation at display time:** Raw names stored as-is from source. Canonical mapping applied at render. This preserves source fidelity and makes it easy to add new ports.
- **Cool-neutral redesign:** Shifted from warm paper palette to cool-neutral (#e8ecf0 background) for a more modern, professional look. Commit 48de298.

### Things Tried
- Railway.app deployment (Dockerfile + railway.toml exist) — moved to Hetzner for more control
- Fraserburgh scraper — built but SWFPA stopped publishing files
- Inline chat on trade dashboard — replaced with shared floating FAB partial

### Non-obvious Constraints
- SWFPA event page uses `var customQuery` (not `window.customQuery`) for event data — scraper must parse this specific JavaScript variable
- Brixham PDF uses DEFRA codes as the regex anchor — species name is everything before the 3-letter code
- Newlyn PDF has stateful grade parsing — continuation lines starting with `(grade)` inherit the previous species
- Lerwick uses SSA web portal (Azure-hosted) with species abbreviation codes that need mapping
- Scrabster HTML has no grades — all prices are grade "ALL"
- Demo port data MUST be isolated — it keeps accidentally leaking into real data views

---

Auto-generated by /claudeupdate in Claude Code.
