# Quayside Codebase Health Audit

**Date:** 2026-03-20
**Scope:** Full codebase — ~12,800 lines of Python across 44 files, 28 Jinja2 templates (~18,800 lines), 1 CSS file (1,070 lines)
**Method:** Read-only analysis of every source file; cross-referenced with grep across the entire codebase

---

## Executive Summary — Top 10 Findings

| # | Severity | Finding | Phase |
|---|----------|---------|-------|
| 1 | **Critical** | Ops dashboard (`/ops/*`) is completely unauthenticated — anyone can trigger pipeline runs, clear quality alerts, apply data fixes | 7 |
| 2 | **High** | HITL confirmation is cosmetic — data is upserted to the live `prices` table on upload, before confirmation | 6 |
| 3 | **High** | `INSERT OR REPLACE` with no pre-storage validation — a bad scrape silently overwrites good historical data | 6 |
| 4 | **High** | Flask `SECRET_KEY` falls back to hardcoded `"dev-secret-change-me"` if env var is unset | 7 |
| 5 | **High** | API ingest endpoint (`/api/v1/ingest`) is completely open if `QUAYSIDE_API_KEY` env var is unset | 7 |
| 6 | **High** | In-memory confirmation tokens lost on every deploy/restart — all pending confirmation links break | 4, 6 |
| 7 | **High** | No SQLite `busy_timeout` — concurrent DB access (scheduler + web + subprocess) fails immediately instead of retrying | 4 |
| 8 | **High** | N+1 query pattern in `build_insights()` — up to 40 separate DB queries per port dashboard page load | 5 |
| 9 | **High** | "Best price per species per port" logic copy-pasted 6+ times across 4 files | 3 |
| 10 | **Medium** | ~60+ hardcoded warm-palette hex values persist across templates after cool-neutral migration | 8 |

---

## Phase 1 — Orientation

The codebase is well-documented (CLAUDE.md is comprehensive), well-organized (clear module separation), and notably clean of commented-out code and lint violations. The architecture is appropriate for its scale: a single-server Flask app with SQLite, APScheduler, and systemd timers.

Key structural observations:
- **44 Python files**, ~12,800 lines total
- **28 templates**, ~18,800 lines (some very large: `trade.html` 3,399 lines, `dashboard.html` 3,056 lines)
- **1 CSS file** (`tokens.css`, 1,070 lines) defines the design system
- **1 test file** with 5 tests covering only the SWFPA/Peterhead scraper
- **2 orphan scripts** at the project root (`species_audit.py`, `scripts/backfill_peterhead.py`)

---

## Phase 2 — Dead Code & Unused Imports

### Unused Imports
None found. All imports across all 44 Python files are actively used.

### Dead Functions

| Severity | File | Function | Notes |
|----------|------|----------|-------|
| Low | `ports.py:67` | `get_active_port_names()` | Never called anywhere. Also has a demo-port isolation bug (see Phase 6). |
| Low | `ports.py:73` | `get_upload_ports()` | Never called anywhere. |
| Low | `http_cache.py:120` | `invalidate()` | Cache invalidation function defined but never called. |
| Low | `db.py:1050` | `get_prices_by_date_for_port()` | Trivial wrapper around `get_prices_by_date()` — callers use the underlying function directly. |

### Unused Constants

| Severity | File | Constant | Notes |
|----------|------|----------|-------|
| Low | `species.py:297` | `CATEGORY_LABELS` | Dictionary mapping category codes to display labels. Never referenced in Python or templates — labels are hardcoded directly in templates. |

### Commented-Out Code
None found. The codebase is clean.

### Orphan Files

| Severity | File | Lines | Notes |
|----------|------|-------|-------|
| Medium | `species_audit.py` (root) | 373 | Standalone diagnostic script that duplicates the entire `_CANONICAL_MAP` from `species.py`. Creates confusion if the canonical map is updated in one place but not the other. |
| Low | `scripts/backfill_peterhead.py` | 63 | One-off data migration script. Served its purpose. |

### Dormant Code

| Severity | File | Notes |
|----------|------|-------|
| Low | `scrapers/fraserburgh.py` | Still wired into the pipeline (`run.py:27`). Executes on every pipeline run but always returns empty because SWFPA stopped publishing Fraserburgh data. Intentionally dormant — will auto-resume if data reappears. Minor unnecessary HTTP request per pipeline run. |

---

## Phase 3 — Duplicate & Redundant Code

### Finding 3.1: "Best price per species per port" — 6+ near-identical implementations
- **Severity:** High
- **Files:** `trade.py:383`, `report.py:260`, `report.py:70`, `helpers.py:960`, `helpers.py:1126`, `helpers.py:1309`, `helpers.py:1418`, `review.py:41`
- **What:** Every file that needs "best price per species per port" re-implements the same loop: iterate rows, normalise species, skip None, compare avg to existing best. The core logic is identical across 6+ locations.
- **Why it matters:** A change to the aggregation logic (e.g., handling a new grade system) must be made in 6+ places. Bugs in one copy won't be fixed in the others.
- **Suggested fix:** Create a single `best_price_per_species_per_port(rows) -> dict[str, dict[str, float]]` utility function.

### Finding 3.2: Percentage change calculation — repeated 15+ times
- **Severity:** Medium
- **Files:** `report.py` (5 locations), `trade.py` (4), `review.py` (4), `helpers.py` (10+)
- **What:** The pattern `pct = round(((new - old) / old) * 100, 1)` with direction/arrow/sign derivation is repeated identically 15+ times.
- **Why it matters:** Inconsistencies creep in (some use `> 0`, some use `>= 0` for direction).
- **Suggested fix:** Create a `pct_change(new, old) -> dict` helper returning `{pct, direction, arrow, pct_str}`.

### Finding 3.3: Same-date DB queries called redundantly in helpers.py
- **Severity:** Medium-High
- **Files:** `helpers.py:952`, `helpers.py:1126`, `helpers.py:1303`, `helpers.py:1371`
- **What:** Four separate functions each independently call `get_all_prices_for_date(date)` fetching the same result set, then each builds its own lookup dict from the same raw data. Called from the same port dashboard route for the same date.
- **Why it matters:** 3 redundant DB queries per page load, plus 3 redundant iterations over the same data.
- **Suggested fix:** Fetch once at the route level and pass into each builder function.

### Finding 3.4: Identical `_extract_lines()` in brixham.py and newlyn.py
- **Severity:** Low
- **Files:** `scrapers/brixham.py:140`, `scrapers/newlyn.py:178`
- **What:** Byte-for-byte identical PDF text extraction function.
- **Suggested fix:** Move to a shared `scrapers/utils.py`.

### Finding 3.5: Ordinal date extraction — same regex in 4 scrapers
- **Severity:** Low-Medium
- **Files:** `scrapers/brixham.py:150`, `scrapers/newlyn.py:188`, `scrapers/lerwick.py:155`, `scrapers/fraserburgh.py:135`
- **What:** All four parse dates with the regex `(\d+)(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})` and convert identically.
- **Suggested fix:** Shared `parse_date_from_text()` utility.

### Finding 3.6: User-Agent header constant — identical dict in all 7 scrapers
- **Severity:** Low
- **Files:** All 7 scraper files
- **What:** The exact same `HEADERS` dict with a Chrome user-agent string.
- **Suggested fix:** Define once in `scrapers/__init__.py`.

### Finding 3.7: `_port_codes()` — identical fallback function in report.py and trade.py
- **Severity:** Medium
- **Files:** `report.py:29`, `trade.py:373`
- **What:** Both define a function calling `get_port_code_map()` with a hardcoded fallback dict. Trade.py's fallback is missing Kinlochbervie.
- **Suggested fix:** Move to `ports.py`.

### Finding 3.8: Numeric parsing — 4 variations of "try float, return None"
- **Severity:** Low
- **Files:** `scrapers/lerwick.py:171`, `scrapers/scrabster.py:124`, `scrapers/fraserburgh.py:157`, `helpers.py:926`
- **What:** All implement `try: float(val) except: None` with minor variations.
- **Suggested fix:** Shared `parse_numeric()` utility.

### Finding 3.9: Synthetic price generation — copy-pasted in db.py
- **Severity:** Medium
- **Files:** `db.py:885` (`seed_demo_data`) and `db.py:995` (`seed_demo_port_data`)
- **What:** Near-identical MD5-based price generation logic.
- **Suggested fix:** Extract shared `_generate_synthetic_prices()` function.

### Finding 3.10: Previous-day price fetching — duplicated 5 times
- **Severity:** Medium
- **Files:** `report.py:286`, `report.py:497`, `trade.py:484`, `helpers.py:1212`, `helpers.py:1389`
- **What:** Pattern of `get_previous_date()` → `get_all_prices_for_date(prev_date)` → loop for best price per species.
- **Suggested fix:** Create `get_previous_day_best_prices(date) -> dict`.

---

## Phase 4 — Flow Conflicts & Race Conditions

### Finding 4.1: In-memory confirmation tokens lost on restart
- **Severity:** High
- **File:** `confirm.py:32`
- **What:** `_confirm_tokens` is a plain `dict` in module memory. Any process restart (deploy, gunicorn reload, crash) permanently orphans all pending tokens. Users who received confirmation emails get dead links. The comment on line 31 acknowledges this: "In production, store in DB."
- **Why it matters:** Deployments happen on every push to `main`. Any upload pending confirmation at deploy time becomes unreachable via its confirmation link.
- **Suggested fix:** Store tokens in a `confirm_token` column on the `uploads` table with an expiry timestamp.

### Finding 4.2: Subprocess pipeline loses tokens too
- **Severity:** High
- **File:** `ops_views.py:548`
- **What:** Manual pipeline trigger at `/ops/run-pipeline` runs `python -m quayside` as a subprocess. If this subprocess processes email uploads and generates confirmation tokens, those tokens exist only in the subprocess's memory and are lost when it exits.
- **Why it matters:** Manual pipeline triggers that process email uploads produce permanently broken confirmation links.
- **Suggested fix:** Same as 4.1 — store tokens in DB.

### Finding 4.3: No SQLite busy_timeout
- **Severity:** High
- **File:** `db.py:17`
- **What:** `get_connection()` enables WAL mode but does not set `busy_timeout`. Default is 0ms — any concurrent write attempt fails immediately with `database is locked` rather than retrying.
- **Why it matters:** APScheduler thread + Flask request thread + subprocess pipeline all write to the same DB. Without `busy_timeout`, the second writer fails instantly.
- **Suggested fix:** Add `conn.execute("PRAGMA busy_timeout=5000")` after WAL pragma.

### Finding 4.4: No overlap protection for scheduled jobs
- **Severity:** Medium
- **File:** `scheduler.py:118`
- **What:** No protection against pipeline and quality check running simultaneously. Pipeline runs quality checks at the end; if the standalone quality job fires at the same time, two quality check runs execute concurrently. Also, manual triggers from `/ops/` can overlap with scheduled runs.
- **Why it matters:** Concurrent quality checks produce duplicate `error_log` entries (no UNIQUE constraint). Concurrent pipeline runs could cause `SQLITE_BUSY` errors.
- **Suggested fix:** Use APScheduler's `max_instances=1` (already default per-job) and add a file lock or database flag to prevent cross-job overlap.

### Finding 4.5: Scheduler reloader guard is inverted (dev-only)
- **Severity:** Medium (development only)
- **File:** `scheduler.py:105`
- **What:** The guard `if os.environ.get("WERKZEUG_RUN_MAIN") == "true": return` prevents the scheduler from starting in Flask's child process (the actual app) and starts it in the parent (reloader) process. In production (gunicorn), `WERKZEUG_RUN_MAIN` is never set, so no effect.
- **Suggested fix:** Invert the condition: `if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and os.environ.get("WERKZEUG_RUN_MAIN") is not None: return`.

### Finding 4.6: Connection leak on exceptions
- **Severity:** Medium
- **File:** `db.py` (pervasive — ~54 functions)
- **What:** Every function follows `conn = get_connection() ... conn.close()` without `try/finally` or context manager. If an exception occurs between open and close, the connection leaks.
- **Why it matters:** Leaked connections hold WAL locks and can block subsequent operations during error cascades.
- **Suggested fix:** Use a context manager pattern for all DB access.

### Finding 4.7: HTTP ETag cache file not thread-safe
- **Severity:** Low
- **File:** `http_cache.py:45`
- **What:** `cached_fetch()` performs read-modify-write on a JSON file without locking. Concurrent access from subprocess + scheduler could overwrite each other's cache entries.
- **Why it matters:** Worst case: one cache entry lost, causing an unnecessary re-fetch.

### Finding 4.8: Error log has no deduplication constraint
- **Severity:** Low
- **File:** `db.py:146`
- **What:** `error_log` table has no UNIQUE constraint (unlike `quality_log`). Concurrent quality runs insert duplicate entries.
- **Why it matters:** Inflated error counts on the dashboard.

---

## Phase 5 — Architecture & Simplification Opportunities

### Finding 5.1: N+1 queries in `build_insights()` — up to 40 DB round-trips
- **Severity:** High
- **File:** `helpers.py:450`
- **What:** `build_insights()` loops over 30 dates calling `get_market_averages_for_date()` for each, then repeats for 5 weekly dates, then 5 more for below-market streaks. That's ~40 separate SQLite queries for a single page load.
- **Why it matters:** Direct impact on port dashboard response time.
- **Suggested fix:** Use `get_market_averages_for_range(start, end)` once — the function already exists in `db.py`.

### Finding 5.2: N+1 queries in `build_performance_overview()` — 10 DB round-trips
- **Severity:** High
- **File:** `helpers.py:735`
- **What:** Calls `get_market_averages_for_date()` in a loop for 5 this-week + 5 last-week dates.
- **Suggested fix:** Same — use the range query.

### Finding 5.3: `ops_dashboard()` is a 536-line monolith with inline SQL
- **Severity:** Medium
- **File:** `ops_views.py:19`
- **What:** Single route handler running ~20 raw SQL queries, building ~15 data structures, passing ~35 template variables. Imports `get_connection` via `__import__()` inline. Bypasses `db.py` entirely.
- **Why it matters:** Unmaintainable; SQL queries are not reusable; no separation of concerns.
- **Suggested fix:** Extract queries into `db.py` and data processing into an `ops_helpers.py`.

### Finding 5.4: `port_dashboard()` passes 37 template variables
- **Severity:** Medium
- **File:** `port_views.py:73`
- **What:** 315-line function with ~40 lines of inline demo-port synthetic data generation.
- **Suggested fix:** Bundle related variables into dicts; extract demo data generation.

### Finding 5.5: Connection-per-query pattern in db.py
- **Severity:** Medium
- **File:** `db.py` (60+ functions)
- **What:** Every function opens and closes its own `sqlite3.connect()`. No connection reuse.
- **Why it matters:** Unnecessary overhead; prevents transaction grouping; risks connection leaks (see 4.6).
- **Suggested fix:** Use Flask's `g.db` pattern for request-scoped connections, or a context manager.

### Finding 5.6: `run.py` repeats scraper boilerplate 6 times
- **Severity:** Medium
- **File:** `run.py:81-181`
- **What:** Each scraper follows the identical 12-line pattern: call `_run_scraper()`, build status dict, log attempt, append results. Copy-pasted 6 times.
- **Suggested fix:** Data-driven scraper registry: `SCRAPERS = [(name, source, fn), ...]` with a shared loop.

### Finding 5.7: `get_market_averages_for_date()` aggregates in Python
- **Severity:** Low
- **File:** `db.py:1201`
- **What:** Fetches per-port best grades then computes min/max/avg/count in Python. SQLite can do this in a single nested query.

### Finding 5.8: helpers.py could be split into 4-5 modules
- **Severity:** Medium
- **File:** `helpers.py` (1,475 lines)
- **What:** Contains 17 functions spanning market positioning, alerts, stats, insights, and utilities.
- **Why it matters:** Organization, not urgency. Functions share data types and imports, so splitting requires care to avoid circular imports.
- **Suggested split:** `market.py` (~250 lines), `alerts.py` (~185), `stats.py` (~300), `insights.py` (~315), keep `helpers.py` (~300 for shared utils).

---

## Phase 6 — Data Integrity & Business Logic Risks

### Finding 6.1: HITL confirmation is cosmetic — data goes live on upload
- **Severity:** High
- **File:** `port_views.py:634`
- **What:** `upsert_prices_with_upload(records, upload_id)` is called immediately on upload, before the user confirms. The "confirmation" step only changes the upload record's status from `pending` to `confirmed` — it does not gate the data. Unconfirmed, potentially incorrect extracted data is live in the `prices` table from the moment of upload.
- **Why it matters:** The HITL workflow, documented as a data quality gate, provides no actual protection. A bad AI extraction goes live instantly.
- **Suggested fix:** Store extracted records in a staging area (e.g., JSON blob on the upload record) and only upsert into `prices` upon confirmation/approval.

### Finding 6.2: INSERT OR REPLACE can silently overwrite good data
- **Severity:** High
- **File:** `db.py:436`
- **What:** The upsert strategy is `INSERT OR REPLACE` on `UNIQUE(date, port, species, grade)`. If a scraper returns malformed data (e.g., `price_avg = 0` due to a parsing bug), it silently overwrites the correct data from a previous successful scrape. Quality checks run AFTER the upsert, so by the time an issue is flagged, the good data is already gone.
- **Why it matters:** No rollback mechanism exists. A single bad scraper run can corrupt an entire day's historical data for a port.
- **Suggested fix:** Add pre-upsert validation: reject records where `price_avg <= 0`, `price_avg > 200`, or date is in the future. Consider a `price_history` table for audit trail.

### Finding 6.3: No pre-storage validation of scraped records
- **Severity:** High
- **File:** `run.py:204`
- **What:** `upsert_prices(all_prices)` is called with the full batch without validation. `PriceRecord` has no validators. No checks for `price_avg <= 0`, `price_avg > 200`, future dates, empty species, or `price_low > price_high`.
- **Why it matters:** Combined with 6.2, bad data overwrites good data with no guard.
- **Suggested fix:** Add a `validate_records()` function called before `upsert_prices()`.

### Finding 6.4: `get_active_port_names()` does not exclude Demo Port
- **Severity:** Medium
- **File:** `ports.py:67`
- **What:** Returns all active ports including Demo Port. Currently unused (so no leak), but is a latent trap for future code.
- **Suggested fix:** Add `data_method != "demo"` filter.

### Finding 6.5: No rejection mechanism for bad uploads
- **Severity:** Medium
- **File:** `port_views.py` (confirmation flow)
- **What:** The confirmation page offers "Looks good" and "Fix something" but no "Reject and remove" option. Combined with 6.1 (data already live), a port operator who sees obviously wrong extracted data has no way to remove it.
- **Suggested fix:** Add a reject/delete action that removes the upserted records.

### Finding 6.6: Disabled quality check — `record_count` commented out
- **Severity:** Low
- **File:** `quality.py:75`
- **What:** `_check_record_count` exists but is commented out. Could catch partial scrapes (3 records instead of usual 50).
- **Suggested fix:** Re-enable or remove the dead code.

### Finding 6.7: Missing quality check — duplicate source writes
- **Severity:** Medium
- **File:** `quality.py`
- **What:** No check for when the same `(date, port, species, grade)` is scraped from two different sources with different prices. Last writer wins silently.
- **Suggested fix:** Add a check comparing `scraped_at` timestamps for multiple writes to the same key within a day.

### Demo Port Isolation — Overall Verdict
The table-level isolation (`demo_prices` vs `prices`) is effective. All aggregate queries and cross-port functions query `prices` only. The `_prices_table()` routing correctly directs Demo Port writes to `demo_prices`. **No critical demo data leaks were found.** The `get_active_port_names()` function (unused) is the only latent gap.

### Species Storage — Overall Verdict
**All clear.** `normalise_species()` is never called in any scraper, extractor, or ingest module. All 60+ calls are in display/analysis layers. The convention is properly followed.

---

## Phase 7 — Security & Best Practice

### Finding 7.1: Ops dashboard completely unauthenticated
- **Severity:** Critical
- **File:** `ops_views.py` (all routes)
- **What:** All ops routes (`/ops`, `/ops/run-pipeline`, `/ops/run-quality-check`, `/ops/quality/clear/*`, `/ops/errors/fix/*`) have zero authentication. Any internet user can view internal data, trigger pipeline runs (which runs `subprocess.run()` on the server), clear quality alerts, and apply data fixes.
- **Why it matters:** An attacker can trigger pipeline runs (DoS), clear quality alerts to hide data issues, or apply auto-fixes to manipulate data. The `require_admin()` function exists in `auth.py` but is never used.
- **Suggested fix:** Add `@require_admin` decorator or `before_request` hook on the ops blueprint.

### Finding 7.2: Flask SECRET_KEY insecure default
- **Severity:** High
- **File:** `app.py:29`
- **What:** `app.secret_key = os.environ.get("QUAYSIDE_SECRET_KEY", "dev-secret-change-me")`. If the env var is unset (misconfigured deployment), an attacker who knows the hardcoded key can forge sessions and CSRF tokens.
- **Suggested fix:** Fail hard on startup if env var is unset in production.

### Finding 7.3: API ingest open when key unset
- **Severity:** High
- **File:** `api_views.py:20`
- **What:** `_API_KEY = os.environ.get("QUAYSIDE_API_KEY", "")`. If empty, the auth check is skipped — anyone can POST arbitrary price data to `/api/v1/ingest`.
- **Suggested fix:** Require key to be set or disable the endpoint when no key is configured.

### Finding 7.4: JSON requests bypass CSRF
- **Severity:** Medium
- **File:** `app.py:64`
- **What:** `if request.is_json: return` — any POST with `Content-Type: application/json` skips CSRF validation. Currently safe because no CORS headers are set (browser blocks cross-origin JSON POSTs via preflight), but would become exploitable if CORS headers were ever added.
- **Suggested fix:** Require `X-CSRF-Token` header on JSON POSTs from the browser.

### Finding 7.5: Upload route has no authentication
- **Severity:** Medium
- **File:** `port_views.py:603`
- **What:** `/port/<slug>/upload` accepts file uploads from anyone without authentication.
- **Suggested fix:** Require authentication or rate limiting.

### Finding 7.6: Session cookies lack `Secure` flag
- **Severity:** Medium
- **File:** `app.py`
- **What:** `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE` not explicitly configured. Site runs over HTTPS in production but cookies could be sent over HTTP.
- **Suggested fix:** Set `SESSION_COOKIE_SECURE = True` and `SESSION_COOKIE_SAMESITE = "Lax"`.

### Finding 7.7: Trade token comparison not timing-safe
- **Severity:** Low
- **File:** `trade_views.py:30`
- **What:** Uses `==` instead of `secrets.compare_digest()` for trade token comparison, unlike the API key check which correctly uses `compare_digest()`.
- **Suggested fix:** Use `secrets.compare_digest()`.

### Finding 7.8: No file type allowlist on uploads
- **Severity:** Medium
- **File:** `port_views.py:616`, `extractors/__init__.py`
- **What:** Files are routed to extractors by extension. Unknown extensions fall through to the AI extractor, sending file content to Claude's API (costs money, potential data leak). No MIME type or magic byte validation.
- **Suggested fix:** Allowlist accepted extensions (`.xls`, `.xlsx`, `.csv`, `.pdf`, `.png`, `.jpg`); reject others.

### Finding 7.9: Database error details exposed in API responses
- **Severity:** Low
- **File:** `api_views.py:130`
- **What:** `{"error": "Database error.", "details": str(e)}` returned to API callers, potentially leaking schema details.
- **Suggested fix:** Log internally, return generic message to client.

### Finding 7.10: No hardcoded secrets found (positive)
API keys, SMTP credentials, and the Anthropic API key are all sourced from environment variables. No `.env` files are committed. `.gitignore` properly excludes `.env` and `.env.*`.

### Finding 7.11: SQL injection — no vulnerabilities found (positive)
All user-supplied values use parameterised queries (`?` placeholders). The one dynamic table name (`_prices_table()`) only returns hardcoded strings. No injection vectors.

---

## Phase 8 — Frontend & Template Audit

### Finding 8.1: Undefined CSS variables in error.html
- **Severity:** High
- **File:** `web/templates/error.html`
- **What:** Uses `var(--fg)` and `var(--accent)` which are not defined in `tokens.css`. Text may render invisible; links may have no color.
- **Suggested fix:** Replace with `var(--ink-body)` and `var(--catch)`.

### Finding 8.2: Warm palette remnants — 60+ hardcoded hex values
- **Severity:** Medium
- **Files:** `landing.html`, `about.html`, `for_ports.html`, `for_traders.html`, `index.html`, `upload_form.html`, `weekly.html`, `monthly.html`, `trade.html`, `dashboard.html`
- **What:** Dozens of warm palette hex codes persist from before the cool-neutral migration: `#7a7060` (warm muted), `#5a5448` (warm body text), `#4a4438` (warm dark), `#3a3428` (warm near-black), `#e8e0d0` (warm grid), `#0f0e0c` (warm tooltip bg). Also present in Chart.js configurations.
- **Why it matters:** Mixed warm and cool tones create visual inconsistency.
- **Suggested fix:** Batch replace: `#7a7060` → `#6a7a88`, `#5a5448` → `#3a4a58`, `#4a4438` → `#0f1820`, `#e8e0d0` → `#c0cad4`, `#0f0e0c` → `#0f1820`.

### Finding 8.3: Border-radius violations (brand rule: max 2px)
- **Severity:** Medium
- **Files:** `landing.html`, `for_ports.html`, `for_traders.html`, `about.html`, `trade.html`, `dashboard.html`, `quality_report.html`, `methodology.html`, `tokens.css`
- **What:** Values of 3px, 4px, 6px, 8px, 12px on rectangular elements. `border-radius: 50%` on circular elements (dots, FABs) is acceptable.
- **Suggested fix:** Change rectangular values > 2px down to 2px.

### Finding 8.4: Box-shadow violations (brand rule: borders not shadows)
- **Severity:** Medium
- **Files:** `landing.html`, `for_ports.html`, `for_traders.html`, `about.html`, `trade.html`, `dashboard.html`, `login.html`, `digest_wrapper.html`, `tokens.css`
- **What:** ~25 instances of decorative `box-shadow` on cards, buttons, mockups.
- **Suggested fix:** Replace cosmetic shadows with `border: 1px solid var(--rule)`. Keep functional shadows (tour spotlight, pulse animation).

### Finding 8.5: Email domain inconsistency
- **Severity:** High
- **Files:** `for_ports.html`, `landing.html`, `about.html`, `for_traders.html`, `trade_gate.html`, `dashboard.html`
- **What:** Three different contact email domains used: `hello@quayside.fish`, `hello@quayside.trade`, `hello@quaysidedata.com`.
- **Why it matters:** Confuses users; some may go to non-functional mailboxes.
- **Suggested fix:** Standardize to one domain.

### Finding 8.6: Marketing page class redefinitions override tokens.css
- **Severity:** Medium
- **Files:** `for_ports.html`, `for_traders.html`, `landing.html`
- **What:** Redefine `.btn-primary`, `.btn-secondary`, `.section-label` with different values from `tokens.css`. Token changes won't propagate.
- **Suggested fix:** Use token definitions or page-specific variants (e.g., `.landing-btn-primary`).

### Finding 8.7: Footer inconsistency
- **Severity:** Medium
- **Files:** `about.html`, `for_ports.html` vs all other pages
- **What:** Only these two pages have footers. `base.html` has no footer. Footer appears/disappears depending on the page.
- **Suggested fix:** Add a shared `_footer.html` partial included from `base.html`.

### Finding 8.8: Inline style overload in marketing templates
- **Severity:** Medium
- **Files:** `for_ports.html:643-727`, `quality_report.html:392-528`, `ops.html`
- **What:** Extensive inline styles where classes should be used.
- **Suggested fix:** Extract to named CSS classes.

### Finding 8.9: `trade_ports.html` content in wrong block
- **Severity:** Low
- **File:** `trade_ports.html`
- **What:** Main page content placed in `{% block scripts %}` instead of `{% block content %}`.
- **Suggested fix:** Move to correct block.

### Overall UX Assessment

| Area | Verdict |
|------|---------|
| **Information hierarchy** | Good — port dashboard and trade dashboard have clear visual hierarchy |
| **User journey** | Mostly clear; upload → confirm flow is well-structured |
| **Empty states** | Good coverage; `errors.html` has "All Clear" state; dashboard handles missing data |
| **Loading feedback** | Partial — AJAX buttons show "Fixing..."/"Fixed" feedback; no skeleton states for initial page loads |
| **Mobile responsiveness** | Most pages have `@media` breakpoints; `quality_report.html` and `ops.html` lack mobile breakpoints |
| **Visual consistency** | Mixed — warm palette remnants create tonal inconsistency between pages |

---

## Phase 9 — Test Coverage

### Existing Tests
One test file: `tests/test_swfpa.py` with 5 tests covering only the SWFPA/Peterhead XLS scraper's happy path. No edge cases, no error cases, no other modules tested.

### Test Infrastructure Issues
- No `conftest.py` — no shared fixtures
- No test database setup — all DB functions point to production DB path
- No Flask test client fixture
- No mocking utilities for HTTP, SMTP, IMAP, or Claude API
- No coverage reporting or minimum threshold

### Top 10 Highest-Risk Untested Areas

| # | File | Area | Risk | Effort |
|---|------|------|------|--------|
| 1 | `db.py` | Upsert logic + demo isolation | Data integrity — the single enforcement point for table routing | Medium |
| 2 | `species.py` | `normalise_species()` + `is_noisy_species()` | Data accuracy — incorrect mappings break cross-port comparisons | **Small** |
| 3 | `quality.py` | All 11 quality checks | Data integrity safety net — false negatives = bad data reaches users | Medium |
| 4 | `helpers.py` | `build_today_data()`, `build_insights()`, `build_competitive_market()` | User-facing accuracy — bugs directly affect what traders see | Medium |
| 5 | `trade.py` | Trade matrix + highlights | Revenue — paid feature at £95/month | Large |
| 6 | `confirm.py` | Token generation, auto-publish logic | Data workflow — controls whether uploads go live | **Small** |
| 7 | `extractors/` | CSV + XLS parsing | Upload reliability — malformed files could produce wrong data | Medium |
| 8 | `run.py` | Pipeline orchestration | System reliability — a bug here stops all data flow | Large |
| 9 | `ingest.py` | Email ingestion, port identification | Data routing — wrong port match = data in wrong dashboard | **Small** |
| 10 | `error_actions.py` | Fix actions, date extraction | Data modification — auto-fixes applied from error dashboard | **Small** |

**Recommended approach:** Start with the "Small" effort items (species.py, confirm.py, ingest.py, error_actions.py) for maximum coverage with minimum work. First step: create a `conftest.py` with an in-memory SQLite fixture.

---

## Priority Fix List

The 15 most important things to address, in order of urgency:

| # | Finding | Severity | Effort | What to do |
|---|---------|----------|--------|-----------|
| 1 | Ops routes unauthenticated (7.1) | Critical | **Small** | Add `@require_admin` to ops blueprint — the function already exists |
| 2 | HITL confirmation is cosmetic (6.1) | High | **Large** | Redesign: stage data in upload record, only upsert to `prices` on approval |
| 3 | No pre-storage validation (6.2, 6.3) | High | **Small** | Add `validate_records()` before `upsert_prices()` — reject price_avg ≤ 0, > 200, future dates |
| 4 | SECRET_KEY insecure fallback (7.2) | High | **Small** | Fail on startup if `QUAYSIDE_SECRET_KEY` is not set |
| 5 | API ingest open when key unset (7.3) | High | **Small** | Return 503 if `QUAYSIDE_API_KEY` is empty |
| 6 | Confirmation tokens in-memory (4.1, 4.2) | High | **Medium** | Store tokens in the `uploads` table |
| 7 | No SQLite busy_timeout (4.3) | High | **Small** | Add `PRAGMA busy_timeout=5000` to `get_connection()` |
| 8 | N+1 queries in helpers.py (5.1, 5.2) | High | **Medium** | Replace per-date loops with `get_market_averages_for_range()` |
| 9 | Best-price-per-species duplication (3.1) | High | **Medium** | Extract shared utility function |
| 10 | Undefined CSS variables in error.html (8.1) | High | **Small** | Replace `--fg` → `--ink-body`, `--accent` → `--catch` |
| 11 | Email domain inconsistency (8.5) | High | **Small** | Standardize all contact emails to one domain |
| 12 | Warm palette remnants (8.2) | Medium | **Medium** | Batch find-and-replace ~60 hex values across templates |
| 13 | Connection leak risk in db.py (4.6) | Medium | **Medium** | Refactor to context manager pattern |
| 14 | Add test infrastructure + species.py tests (9) | Medium | **Small** | Create conftest.py + test `normalise_species()` and `is_noisy_species()` |
| 15 | Session cookie security flags (7.6) | Medium | **Small** | Set `SESSION_COOKIE_SECURE=True`, `SAMESITE="Lax"` |
