from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from quayside.models import PriceRecord

# Allow DB path override via env var (for Railway persistent volume)
_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "quayside.db"
DB_PATH = Path(os.environ.get("QUAYSIDE_DB_PATH", str(_DEFAULT_DB)))


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            port TEXT NOT NULL,
            species TEXT NOT NULL,
            grade TEXT NOT NULL,
            price_low REAL,
            price_high REAL,
            price_avg REAL,
            weight_kg REAL,
            scraped_at TEXT NOT NULL,
            upload_id INTEGER,
            UNIQUE(date, port, species, grade)
        );

        CREATE TABLE IF NOT EXISTS ports (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            region TEXT NOT NULL,
            data_method TEXT NOT NULL DEFAULT 'scraper',
            contact_email TEXT,
            contact_name TEXT,
            status TEXT NOT NULL DEFAULT 'inactive',
            created_at TEXT NOT NULL,
            magic_link_token TEXT
        );

        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            port_slug TEXT NOT NULL,
            date TEXT NOT NULL,
            method TEXT NOT NULL,
            raw_file_path TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            uploaded_at TEXT NOT NULL,
            confirmed_at TEXT,
            confirmed_by TEXT,
            extraction_confidence REAL,
            record_count INTEGER DEFAULT 0,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS extraction_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            row_index INTEGER,
            original_value TEXT,
            corrected_value TEXT,
            corrected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ran_at TEXT NOT NULL,
            port TEXT NOT NULL,
            success INTEGER NOT NULL,
            record_count INTEGER DEFAULT 0,
            error_type TEXT,
            error_msg TEXT,
            data_date TEXT
        );

        CREATE TABLE IF NOT EXISTS quality_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at TEXT NOT NULL,
            check_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            port TEXT NOT NULL,
            date TEXT NOT NULL,
            species TEXT,
            grade TEXT,
            value REAL,
            expected REAL,
            message TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'trade',
            port_slug TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS landings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            port TEXT NOT NULL,
            vessel_name TEXT NOT NULL,
            vessel_code TEXT NOT NULL,
            species TEXT NOT NULL,
            boxes INTEGER NOT NULL,
            boxes_msc INTEGER NOT NULL,
            scraped_at TEXT NOT NULL,
            UNIQUE(date, port, vessel_name, vessel_code, species)
        );

        CREATE TABLE IF NOT EXISTS demo_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            port TEXT NOT NULL,
            species TEXT NOT NULL,
            grade TEXT NOT NULL,
            price_low REAL,
            price_high REAL,
            price_avg REAL,
            weight_kg REAL,
            scraped_at TEXT NOT NULL,
            upload_id INTEGER,
            boxes INTEGER,
            defra_code TEXT,
            week_avg REAL,
            size_band TEXT,
            UNIQUE(date, port, species, grade)
        );

        CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at TEXT NOT NULL,
            check_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            port TEXT,
            species TEXT,
            detail TEXT,
            status TEXT DEFAULT 'open',
            resolved_at TEXT,
            resolution TEXT
        );
    """)

    # Migrations: add columns that were introduced after initial deploy
    _migrate(conn)
    conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply any schema migrations needed for existing DBs."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(prices)").fetchall()}
    if "scraped_at" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN scraped_at TEXT NOT NULL DEFAULT ''")
    if "upload_id" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN upload_id INTEGER")
    if "weight_kg" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN weight_kg REAL")
    if "boxes" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN boxes INTEGER")
    if "defra_code" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN defra_code TEXT")
    if "week_avg" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN week_avg REAL")
    if "size_band" not in existing:
        conn.execute("ALTER TABLE prices ADD COLUMN size_band TEXT")
    # demo_prices table — isolated store for Demo Port data (never mixed with real prices)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS demo_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                port TEXT NOT NULL,
                species TEXT NOT NULL,
                grade TEXT NOT NULL,
                price_low REAL,
                price_high REAL,
                price_avg REAL,
                weight_kg REAL,
                scraped_at TEXT NOT NULL,
                upload_id INTEGER,
                boxes INTEGER,
                defra_code TEXT,
                week_avg REAL,
                size_band TEXT,
                UNIQUE(date, port, species, grade)
            )
        """)
    except Exception:
        pass
    # Migrate existing demo_prices tables to add missing columns
    existing_demo = {row[1] for row in conn.execute("PRAGMA table_info(demo_prices)").fetchall()}
    if existing_demo:
        for col, typ in [("upload_id", "INTEGER"), ("boxes", "INTEGER"),
                         ("defra_code", "TEXT"), ("week_avg", "REAL"), ("size_band", "TEXT")]:
            if col not in existing_demo:
                try:
                    conn.execute(f"ALTER TABLE demo_prices ADD COLUMN {col} {typ}")
                except Exception:
                    pass
    # Clean up any Demo Port data that leaked into the prices table
    conn.execute("DELETE FROM prices WHERE port = 'Demo Port'")
    existing_landings = {row[1] for row in conn.execute("PRAGMA table_info(landings)").fetchall()}
    if existing_landings and "scraped_at" not in existing_landings:
        conn.execute("ALTER TABLE landings ADD COLUMN scraped_at TEXT NOT NULL DEFAULT ''")
    # scrape_log table (created in init_db for new DBs; add for existing DBs)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scrape_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ran_at TEXT NOT NULL,
                port TEXT NOT NULL,
                success INTEGER NOT NULL,
                record_count INTEGER DEFAULT 0,
                error_type TEXT,
                error_msg TEXT,
                data_date TEXT
            )
        """)
    except Exception:
        pass
    # Add data_date column to existing scrape_log tables
    existing_scrape_cols = {row[1] for row in conn.execute("PRAGMA table_info(scrape_log)").fetchall()}
    if "data_date" not in existing_scrape_cols:
        try:
            conn.execute("ALTER TABLE scrape_log ADD COLUMN data_date TEXT")
        except Exception:
            pass
    # quality_log table
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT NOT NULL,
                check_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                port TEXT NOT NULL,
                date TEXT NOT NULL,
                species TEXT,
                grade TEXT,
                value REAL,
                expected REAL,
                message TEXT NOT NULL
            )
        """)
    except Exception:
        pass
    # Deduplicate quality_log and add unique index to prevent future duplicates.
    # Runs safely on both new and existing DBs.
    existing_indexes = {
        row[1] for row in conn.execute("PRAGMA index_list(quality_log)").fetchall()
    }
    if "quality_log_unique" not in existing_indexes:
        # Remove duplicate rows first (keep lowest id per unique key)
        conn.execute("""
            DELETE FROM quality_log WHERE id NOT IN (
                SELECT MIN(id) FROM quality_log
                GROUP BY check_type, severity, port, date,
                         COALESCE(species, ''), COALESCE(grade, '')
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX quality_log_unique
            ON quality_log(check_type, severity, port, date,
                           COALESCE(species, ''), COALESCE(grade, ''))
        """)
    # Add cleared column to quality_log (for user-acknowledged dismissals)
    existing_quality = {row[1] for row in conn.execute("PRAGMA table_info(quality_log)").fetchall()}
    if "cleared" not in existing_quality:
        conn.execute("ALTER TABLE quality_log ADD COLUMN cleared INTEGER DEFAULT 0")
    # error_log table (for error dashboard)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanned_at TEXT NOT NULL,
                check_name TEXT NOT NULL,
                severity TEXT NOT NULL,
                port TEXT,
                species TEXT,
                detail TEXT,
                status TEXT DEFAULT 'open',
                resolved_at TEXT,
                resolution TEXT
            )
        """)
    except Exception:
        pass
    # trade_feedback table
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                message TEXT NOT NULL,
                page_context TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    except Exception:
        pass
    # users table
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'trade',
                port_slug TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    except Exception:
        pass
    # Add onboarding_completed_at column to users table
    existing_users = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if existing_users and "onboarding_completed_at" not in existing_users:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN onboarding_completed_at TEXT")
        except Exception:
            pass
    conn.commit()


def insert_trade_feedback(name: str, message: str, page_context: str = "") -> None:
    """Store a trade dashboard feedback submission."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO trade_feedback (name, message, page_context) VALUES (?, ?, ?)",
        (name or "", message, page_context),
    )
    conn.commit()
    conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    """Return user row as dict, or None if not found."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    """Return user row as dict, or None if not found."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email: str, password_hash: str, role: str, port_slug: str | None = None) -> int:
    """Insert a new user and return their id."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, role, port_slug) VALUES (?, ?, ?, ?)",
        (email.lower().strip(), password_hash, role, port_slug),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return user_id


def mark_onboarding_complete(user_id: int) -> None:
    """Set onboarding_completed_at for the given user."""
    conn = get_connection()
    conn.execute(
        "UPDATE users SET onboarding_completed_at = datetime('now') WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def has_completed_onboarding(user_id: int) -> bool:
    """Return True if the user has completed onboarding."""
    conn = get_connection()
    row = conn.execute(
        "SELECT onboarding_completed_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return bool(row and row[0])


def log_scrape_attempt(
    port: str,
    success: bool,
    record_count: int = 0,
    error_type: str | None = None,
    error_msg: str | None = None,
    data_date: str | None = None,
) -> None:
    """Record a scrape attempt result in scrape_log."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO scrape_log (ran_at, port, success, record_count, error_type, error_msg, data_date)
           VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?)""",
        (port, 1 if success else 0, record_count, error_type, error_msg, data_date),
    )
    conn.commit()
    conn.close()


def upsert_prices(records: list[PriceRecord]) -> int:
    if not records:
        return 0
    conn = get_connection()
    # Group by target table so Demo Port data goes to demo_prices
    by_table: dict[str, list] = {}
    for r in records:
        table = _prices_table(r.port)
        by_table.setdefault(table, []).append((
            r.date, r.port, r.species, r.grade,
            r.price_low, r.price_high, r.price_avg, r.weight_kg, r.scraped_at,
            r.boxes, r.defra_code, r.week_avg, r.size_band,
        ))
    for table, rows in by_table.items():
        conn.executemany(
            f"""INSERT OR REPLACE INTO {table}
               (date, port, species, grade, price_low, price_high, price_avg, weight_kg, scraped_at,
                boxes, defra_code, week_avg, size_band)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    conn.commit()
    count = len(records)
    conn.close()
    return count


def get_prices_by_date(date: str, port: str) -> list[tuple]:
    table = _prices_table(port)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT date, port, species, grade, price_low, price_high, price_avg, weight_kg, boxes
           FROM {table} WHERE date = ? AND port = ?
           ORDER BY species, grade""",
        (date, port),
    ).fetchall()
    conn.close()
    return rows


def get_all_prices_for_date(date: str, exclude_demo: bool = False) -> list[tuple]:
    """All real-port price rows for a given date, across all ports.

    Demo Port data lives in the separate 'demo_prices' table and is never
    included here regardless of the exclude_demo flag (kept for backward compat).

    Returns 9-tuples: (date, port, species, grade, price_low, price_high, price_avg, weight_kg, boxes)
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT date, port, species, grade, price_low, price_high, price_avg, weight_kg, boxes
           FROM prices WHERE date = ?
           ORDER BY species, port, grade""",
        (date,),
    ).fetchall()
    conn.close()
    return rows


def get_latest_date() -> str | None:
    """Most recent date in the prices table."""
    conn = get_connection()
    row = conn.execute("SELECT MAX(date) FROM prices").fetchone()
    conn.close()
    return row[0] if row else None


def get_latest_rich_date(min_ports: int = 2) -> str | None:
    """Most recent date with data from at least `min_ports` ports.

    Prevents sparse weekend/partial data from becoming the default digest date.
    Falls back to get_latest_date() if no multi-port date exists.
    """
    conn = get_connection()
    row = conn.execute(
        """SELECT date FROM prices
           GROUP BY date
           HAVING COUNT(DISTINCT port) >= ?
           ORDER BY date DESC
           LIMIT 1""",
        (min_ports,),
    ).fetchone()
    conn.close()
    if row:
        return row[0]
    return get_latest_date()


def get_latest_port_date(port: str) -> str | None:
    """Most recent date with price data for a specific port."""
    table = _prices_table(port)
    conn = get_connection()
    row = conn.execute(
        f"SELECT MAX(date) FROM {table} WHERE port = ?", (port,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_last_scrape_info() -> dict:
    """Returns timestamps of the last scrape check and last successful data receipt.

    Returns:
        {"last_checked": "2026-03-18T10:15:00" | None,
         "last_received": "2026-03-17T10:12:00" | None}
    """
    conn = get_connection()
    last_checked_row = conn.execute(
        "SELECT MAX(ran_at) FROM scrape_log"
    ).fetchone()
    last_received_row = conn.execute(
        "SELECT MAX(ran_at) FROM scrape_log WHERE success = 1 AND record_count > 0"
    ).fetchone()
    conn.close()
    return {
        "last_checked": last_checked_row[0] if last_checked_row else None,
        "last_received": last_received_row[0] if last_received_row else None,
    }


def get_previous_date(date: str) -> str | None:
    """Most recent date before the given date (for day-over-day comparison)."""
    conn = get_connection()
    row = conn.execute("SELECT MAX(date) FROM prices WHERE date < ?", (date,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_prices_for_date_range(start_date: str, end_date: str) -> list[tuple]:
    """All price rows between two dates inclusive, across all ports."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT date, port, species, grade, price_low, price_high, price_avg
           FROM prices WHERE date >= ? AND date <= ?
           ORDER BY date, species, port, grade""",
        (start_date, end_date),
    ).fetchall()
    conn.close()
    return rows


def get_all_time_market_stats() -> tuple[str | None, float | None]:
    """Returns (earliest_price_date, all_time_avg_price) across all non-demo prices."""
    conn = get_connection()
    row = conn.execute(
        "SELECT MIN(date), AVG(price_avg) FROM prices WHERE price_avg IS NOT NULL"
    ).fetchone()
    conn.close()
    if row and row[0]:
        return row[0], round(row[1], 2) if row[1] else None
    return None, None


def get_db_stats() -> dict:
    """Returns headline counts for the data credentials card."""
    conn = get_connection()
    row = conn.execute(
        """SELECT
            COUNT(*) AS total_records,
            COUNT(DISTINCT port) AS total_ports,
            COUNT(DISTINCT date) AS total_trading_days,
            MIN(date) AS earliest_date
           FROM prices WHERE price_avg IS NOT NULL"""
    ).fetchone()
    conn.close()
    if row and row[0]:
        return {
            "total_records": row[0],
            "total_ports": row[1],
            "total_trading_days": row[2],
            "earliest_date": row[3],
        }
    return {"total_records": 0, "total_ports": 0, "total_trading_days": 0, "earliest_date": None}


def get_trading_dates(start_date: str, end_date: str) -> list[str]:
    """Distinct dates with price data in a range, sorted ascending."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT DISTINCT date FROM prices
           WHERE date >= ? AND date <= ?
           ORDER BY date""",
        (start_date, end_date),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_trading_dates_recent(n: int = 10) -> list[str]:
    """Most recent N dates where at least 2 ports reported, newest first."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT date FROM prices
           GROUP BY date HAVING COUNT(DISTINCT port) >= 2
           ORDER BY date DESC LIMIT ?""",
        (n,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_port_auction_dates(port: str, limit: int = 20) -> list[str]:
    """Most recent auction dates for a specific port, newest first."""
    table = _prices_table(port)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT DISTINCT date FROM {table}
           WHERE port = ?
           ORDER BY date DESC
           LIMIT ?""",
        (port, limit),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# --- Port management ---


def upsert_port(
    slug: str,
    name: str,
    code: str,
    region: str,
    data_method: str = "scraper",
    contact_email: str | None = None,
    contact_name: str | None = None,
    status: str = "active",
) -> None:
    """Insert or update a port record."""
    conn = get_connection()
    token = secrets.token_urlsafe(32)
    conn.execute(
        """INSERT INTO ports (slug, name, code, region, data_method,
           contact_email, contact_name, status, created_at, magic_link_token)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
           ON CONFLICT(slug) DO UPDATE SET
             name=excluded.name, code=excluded.code, region=excluded.region,
             data_method=excluded.data_method, contact_email=excluded.contact_email,
             contact_name=excluded.contact_name, status=excluded.status""",
        (slug, name, code, region, data_method, contact_email, contact_name, status, token),
    )
    conn.commit()
    conn.close()


def get_port(slug: str) -> dict | None:
    """Fetch a single port by slug."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM ports WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_port_by_token(token: str) -> dict | None:
    """Fetch a port by its magic link token."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM ports WHERE magic_link_token = ?", (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_ports(status: str | None = None) -> list[dict]:
    """Fetch all ports, optionally filtered by status."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    if status:
        rows = conn.execute(
            "SELECT * FROM ports WHERE status = ? ORDER BY name", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM ports ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_port_count() -> int:
    """Return count of live (active) ports, excluding the demo port."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM ports WHERE status = 'active' AND slug != 'demo'"
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_port_codes() -> dict[str, str]:
    """Return {port_name: port_code} mapping from the ports table.

    Falls back to empty dict if ports table has no rows or doesn't exist yet.
    """
    conn = get_connection()
    try:
        rows = conn.execute("SELECT name, code FROM ports").fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return {name: code for name, code in rows}


# --- Upload management ---


def create_upload(
    port_slug: str,
    date: str,
    method: str,
    raw_file_path: str | None = None,
    extraction_confidence: float | None = None,
    record_count: int = 0,
) -> int:
    """Create an upload record, return its id."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO uploads
           (port_slug, date, method, raw_file_path, status, uploaded_at,
            extraction_confidence, record_count)
           VALUES (?, ?, ?, ?, 'pending', datetime('now'), ?, ?)""",
        (port_slug, date, method, raw_file_path, extraction_confidence, record_count),
    )
    conn.commit()
    upload_id = cur.lastrowid
    conn.close()
    return upload_id


def get_upload(upload_id: int) -> dict | None:
    """Fetch a single upload by id."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def confirm_upload(upload_id: int, confirmed_by: str | None = None) -> None:
    """Mark an upload as confirmed."""
    conn = get_connection()
    conn.execute(
        """UPDATE uploads SET status = 'confirmed', confirmed_at = datetime('now'),
           confirmed_by = ? WHERE id = ?""",
        (confirmed_by, upload_id),
    )
    conn.commit()
    conn.close()


def auto_publish_upload(upload_id: int) -> None:
    """Mark a pending upload as auto-published (no confirmation received)."""
    conn = get_connection()
    conn.execute(
        "UPDATE uploads SET status = 'auto_published' WHERE id = ? AND status = 'pending'",
        (upload_id,),
    )
    conn.commit()
    conn.close()


def get_pending_uploads(older_than_hours: int = 2) -> list[dict]:
    """Fetch uploads still pending confirmation past the timeout."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM uploads
           WHERE status = 'pending'
           AND uploaded_at < datetime('now', ? || ' hours')""",
        (f"-{older_than_hours}",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_correction(
    upload_id: int, field: str, row_index: int | None,
    original_value: str, corrected_value: str,
) -> None:
    """Log a correction made during HITL confirmation."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO extraction_corrections
           (upload_id, field, row_index, original_value, corrected_value, corrected_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))""",
        (upload_id, field, row_index, original_value, corrected_value),
    )
    conn.commit()
    conn.close()


def upsert_prices_with_upload(records: list[PriceRecord], upload_id: int) -> int:
    """Upsert price records linked to a specific upload."""
    if not records:
        return 0
    conn = get_connection()
    # Group by target table so Demo Port data goes to demo_prices
    by_table: dict[str, list] = {}
    for r in records:
        table = _prices_table(r.port)
        by_table.setdefault(table, []).append((
            r.date, r.port, r.species, r.grade,
            r.price_low, r.price_high, r.price_avg, r.weight_kg, r.scraped_at, upload_id,
            r.boxes, r.defra_code, r.week_avg, r.size_band,
        ))
    for table, rows in by_table.items():
        conn.executemany(
            f"""INSERT OR REPLACE INTO {table}
               (date, port, species, grade, price_low, price_high, price_avg, weight_kg, scraped_at,
                upload_id, boxes, defra_code, week_avg, size_band)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    conn.commit()
    count = len(records)
    conn.close()
    return count


# --- Demo Port isolation ---

def _prices_table(port: str) -> str:
    """Return the correct prices table name for a given port name.

    Demo Port data lives in 'demo_prices' to keep it completely isolated
    from real market data. All other ports use the 'prices' table.
    """
    return "demo_prices" if port == "Demo Port" else "prices"


# --- Dashboard queries ---


def get_port_prices_history(port: str, days: int = 30) -> list[tuple]:
    """Price history for a single port over the last N days."""
    table = _prices_table(port)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT date, species, grade, price_low, price_high, price_avg
           FROM {table}
           WHERE port = ? AND date >= date('now', ? || ' days')
           ORDER BY date DESC, species, grade""",
        (port, f"-{days}"),
    ).fetchall()
    conn.close()
    return rows


def seed_demo_data() -> None:
    """Seed 30 days of realistic price data for 5 ports. Idempotent — skips if data exists."""
    if get_latest_date() is not None:
        return

    # Port → (species, base_price, grade_prefix, grade_count)
    # Species names match raw scraped names (normalised at report time by species.py)
    port_species: dict[str, list[tuple[str, float]]] = {
        "Peterhead": [
            ("Haddock", 2.35), ("Cod", 3.20), ("Monks", 7.80), ("Whiting", 1.45),
            ("Saithe", 1.60), ("Megrim", 4.50), ("Lemons", 5.20), ("Plaice", 3.10),
            ("Ling", 2.80), ("Hake", 4.90), ("Witches", 2.60), ("Catfish Scottish", 2.10),
            ("Turbot", 9.50), ("Halibut", 12.00), ("Brill", 8.20), ("Skate", 2.40),
            ("Mackerel", 1.20), ("Squid", 5.50), ("Pollack", 2.90), ("Dab", 1.30),
        ],
        "Brixham": [
            ("Sole", 11.50), ("Monks", 8.10), ("Cod", 3.50), ("Haddock", 2.50),
            ("Plaice", 3.30), ("Turbot", 10.20), ("Brill", 8.80), ("Lemons", 5.50),
            ("Squid", 6.00), ("Cuttlefish", 3.80), ("John Dory", 9.00), ("Red Mullet", 7.20),
            ("Gurnard", 2.20), ("Skate", 2.60), ("Megrim", 4.30), ("Hake", 5.10),
            ("Pollack", 3.10), ("Whiting", 1.55),
        ],
        "Newlyn": [
            ("Monk Or Anglers", 7.60), ("Sole", 11.00), ("Hake", 4.70), ("Cod", 3.40),
            ("Pollack", 3.00), ("Turbot", 9.80), ("John Dory", 8.50), ("Red Mullet", 6.80),
            ("Lemons", 5.00), ("Plaice", 2.90), ("Squid", 5.80), ("Lobster", 14.50),
            ("Brill", 8.50), ("Mackerel", 1.30), ("Gurnard", 2.00),
        ],
        "Scrabster": [
            ("Cod", 3.30), ("Haddock", 2.40), ("Monks", 7.50), ("Whiting", 1.40),
            ("Saithe", 1.55), ("Ling", 2.70), ("Lemons", 4.80), ("Megrim", 4.20),
            ("Plaice", 2.80), ("Hake", 4.60), ("Skate", 2.30), ("Halibut", 11.50),
        ],
        "Lerwick": [
            ("Haddock", 2.30), ("Cod", 3.10), ("Monks", 7.40), ("Whiting", 1.35),
            ("Saithe", 1.50), ("Ling", 2.60), ("Megrim", 4.10), ("Lemons", 4.70),
            ("Mackerel", 1.10), ("Halibut", 11.80),
        ],
    }

    # Grades per port
    port_grades: dict[str, list[str]] = {
        "Peterhead": ["A1", "A2", "A3"],
        "Brixham": ["1", "2", "3", "4", "5"],
        "Newlyn": [""],
        "Scrabster": [""],
        "Lerwick": [""],
    }

    today = datetime.now()
    records: list[PriceRecord] = []

    for day_offset in range(30):
        date = today - timedelta(days=day_offset)
        # Skip weekends
        if date.weekday() >= 5:
            continue
        date_str = date.strftime("%Y-%m-%d")

        for port_name, species_list in port_species.items():
            grades = port_grades[port_name]
            # Use 1-2 grades for graded ports
            num_grades = min(2, len(grades)) if grades[0] else 1

            for species_name, base_price in species_list:
                for g_idx in range(num_grades):
                    grade = grades[g_idx] if grades[0] else ""

                    # Deterministic but varied price: hash of (date, port, species, grade)
                    seed_str = f"{date_str}:{port_name}:{species_name}:{grade}"
                    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
                    # Variation: ±10% from base, plus a gentle trend over 30 days
                    variation = ((h % 200) - 100) / 1000  # -0.10 to +0.10
                    trend = day_offset * 0.002  # older days slightly cheaper
                    price_avg = round(base_price * (1 + variation - trend), 2)

                    # Lower grades get lower prices
                    if g_idx > 0:
                        price_avg = round(price_avg * 0.85, 2)

                    spread = round(price_avg * 0.08, 2)  # 8% spread
                    price_low = round(price_avg - spread, 2)
                    price_high = round(price_avg + spread, 2)

                    records.append(PriceRecord(
                        date=date_str,
                        port=port_name,
                        species=species_name,
                        grade=grade,
                        price_low=price_low,
                        price_high=price_high,
                        price_avg=price_avg,
                        scraped_at=date.isoformat(),
                    ))

    upsert_prices(records)


def get_latest_scraped_at(port: str, date: str) -> str | None:
    """Return the most recent scraped_at timestamp for a port on a given date."""
    table = _prices_table(port)
    conn = get_connection()
    row = conn.execute(
        f"SELECT MAX(scraped_at) FROM {table} WHERE port = ? AND date = ?",
        (port, date),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def seed_demo_port_data() -> None:
    """Seed 90 days of realistic price data for the Demo Port.

    Always runs — refreshes demo data so the dashboard always looks current.
    Writes exclusively to the 'demo_prices' table — never touches 'prices'.
    Uses a fixed species/grade set matching a typical Scottish demersal port.
    """
    PORT_NAME = "Demo Port"
    species_list: list[tuple[str, float]] = [
        ("Haddock", 2.35), ("Cod", 3.20), ("Monks", 7.80), ("Whiting", 1.45),
        ("Saithe", 1.60), ("Megrim", 4.50), ("Lemons", 5.20), ("Plaice", 3.10),
        ("Ling", 2.80), ("Hake", 4.90), ("Witches", 2.60), ("Turbot", 9.50),
        ("Halibut", 12.00), ("Brill", 8.20), ("Skate", 2.40), ("Mackerel", 1.20),
    ]
    grades = ["A1", "A2"]

    today = datetime.now()
    rows = []

    for day_offset in range(90):
        date = today - timedelta(days=day_offset)
        if date.weekday() >= 5:
            continue
        date_str = date.strftime("%Y-%m-%d")

        for species_name, base_price in species_list:
            for g_idx, grade in enumerate(grades):
                seed_str = f"{date_str}:{PORT_NAME}:{species_name}:{grade}"
                h = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
                variation = ((h % 200) - 100) / 1000
                trend = day_offset * 0.002
                price_avg = round(base_price * (1 + variation - trend), 2)
                if g_idx > 0:
                    price_avg = round(price_avg * 0.85, 2)
                spread = round(price_avg * 0.08, 2)
                rows.append((
                    date_str, PORT_NAME, species_name, grade,
                    round(price_avg - spread, 2),
                    round(price_avg + spread, 2),
                    price_avg,
                    None,  # weight_kg
                    date.isoformat(),
                ))

    conn = get_connection()
    conn.executemany(
        """INSERT OR REPLACE INTO demo_prices
           (date, port, species, grade, price_low, price_high, price_avg, weight_kg, scraped_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()


def get_prices_by_date_for_port(date: str, port: str) -> list[tuple]:
    """Price rows for a specific port on a specific date (same as get_prices_by_date)."""
    return get_prices_by_date(date, port)


def get_same_day_last_week(port: str, date: str) -> dict[str, dict]:
    """Get prices for the same weekday one week ago for a port.

    Returns {(species, grade): {price_avg, price_low, price_high}}.
    """
    table = _prices_table(port)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT species, grade, price_low, price_high, price_avg
           FROM {table}
           WHERE port = ? AND date = date(?, '-7 days')""",
        (port, date),
    ).fetchall()
    conn.close()
    return {
        (r[0], r[1]): {"price_avg": r[4], "price_low": r[2], "price_high": r[3]}
        for r in rows
    }


def get_species_availability_gaps(port: str, date: str) -> list[str]:
    """Species active in prior 25 days but absent in last 5 days for a port.

    Returns list of species names.
    """
    table = _prices_table(port)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT DISTINCT species FROM {table}
           WHERE port = ?
             AND date > date(?, '-30 days')
             AND date <= date(?, '-5 days')
             AND species NOT IN (
                 SELECT DISTINCT species FROM {table}
                 WHERE port = ? AND date > date(?, '-5 days') AND date <= ?
             )""",
        (port, date, date, port, date, date),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_seasonal_comparison(port: str, date: str) -> dict[str, float]:
    """Average price per species for the same week one year ago.

    Returns {species: avg_price} or empty dict if no data exists.
    """
    table = _prices_table(port)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT species, AVG(price_avg) as avg_price
           FROM {table}
           WHERE port = ?
             AND date >= date(?, '-1 year', '-3 days')
             AND date <= date(?, '-1 year', '+3 days')
             AND price_avg IS NOT NULL
           GROUP BY species""",
        (port, date, date),
    ).fetchall()
    conn.close()
    return {r[0]: round(r[1], 2) for r in rows}


def get_market_averages_for_range(
    start_date: str, end_date: str,
) -> dict[str, dict[str, float]]:
    """Per-species market average by date for a date range.

    Returns {date: {species: avg_across_ports}}.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT date, species, AVG(price_avg) as market_avg
           FROM (
               SELECT date, species, port, MAX(price_avg) as price_avg
               FROM prices
               WHERE date >= ? AND date <= ? AND price_avg IS NOT NULL
               GROUP BY date, port, species
           )
           GROUP BY date, species""",
        (start_date, end_date),
    ).fetchall()
    conn.close()

    from collections import defaultdict
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for date, species, market_avg in rows:
        result[date][species] = round(market_avg, 2)
    return dict(result)


def get_30day_species_averages(date: str) -> dict[str, float]:
    """Rolling 30-trading-day average price per raw species, ending the day before date.

    Uses best-per-port-then-average methodology (matching market avg calculations):
    for each (date, port, species), take MAX(price_avg) across grades, then AVG
    across ports per (date, species), then AVG across dates.

    Uses ~45 calendar days to capture ~30 trading days.
    Returns {raw_species_name: avg_price}.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT species, AVG(market_avg) as thirty_day_avg
           FROM (
               SELECT date, species, AVG(port_best) as market_avg
               FROM (
                   SELECT date, port, species, MAX(price_avg) as port_best
                   FROM prices
                   WHERE date < ? AND date >= date(?, '-45 days') AND price_avg IS NOT NULL
                   GROUP BY date, port, species
               )
               GROUP BY date, species
           )
           GROUP BY species""",
        (date, date),
    ).fetchall()
    conn.close()
    return {species: round(avg, 2) for species, avg in rows if avg}


def get_30day_port_species_averages(date: str) -> dict[tuple[str, str], tuple[float, int]]:
    """Rolling 30-trading-day average price per (port, raw_species), ending the day before date.

    Uses MAX(price_avg) per (date, port, species) across grades, then AVGs over days.
    trade_days = number of distinct dates that port traded that species in the window.

    Uses ~45 calendar days to capture ~30 trading days.
    Returns {(port, raw_species): (avg_price, trade_day_count)}.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT port, species, AVG(port_best) as avg_price, COUNT(DISTINCT date) as trade_days
           FROM (
               SELECT date, port, species, MAX(price_avg) as port_best
               FROM prices
               WHERE date < ? AND date >= date(?, '-45 days') AND price_avg IS NOT NULL
               GROUP BY date, port, species
           )
           GROUP BY port, species""",
        (date, date),
    ).fetchall()
    conn.close()
    return {(port, species): (round(avg, 2), trade_days) for port, species, avg, trade_days in rows if avg}


def get_market_averages_for_date(date: str) -> dict[str, dict]:
    """Per-species market stats across all ports for a given date.

    Returns {species: {avg: float, min: float, max: float, port_count: int, ports: {port: price}}}.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT port, species, MAX(price_avg) as best_avg
           FROM prices
           WHERE date = ? AND price_avg IS NOT NULL
           GROUP BY port, species""",
        (date,),
    ).fetchall()
    conn.close()

    from collections import defaultdict
    species_data: dict[str, dict[str, float]] = defaultdict(dict)
    for port, species, best_avg in rows:
        species_data[species][port] = best_avg

    result = {}
    for species, port_prices in species_data.items():
        prices = list(port_prices.values())
        result[species] = {
            "avg": sum(prices) / len(prices),
            "min": min(prices),
            "max": max(prices),
            "port_count": len(prices),
            "ports": dict(port_prices),
        }
    return result


def get_quality_issues(days: int = 7) -> list[dict]:
    """Return quality issues logged in the last `days` days that haven't been cleared, newest first."""
    conn = get_connection()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT id, checked_at, check_type, severity, port, date, species, grade,
                  value, expected, message
           FROM quality_log
           WHERE checked_at >= ? AND (cleared IS NULL OR cleared = 0)
           ORDER BY checked_at DESC, severity DESC""",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "checked_at": r[1],
            "check_type": r[2],
            "severity": r[3],
            "port": r[4],
            "date": r[5],
            "species": r[6],
            "grade": r[7],
            "value": r[8],
            "expected": r[9],
            "message": r[10],
        }
        for r in rows
    ]


def clear_quality_issue(issue_id: int) -> None:
    """Mark a quality issue as cleared (acknowledged by operator)."""
    conn = get_connection()
    conn.execute("UPDATE quality_log SET cleared = 1 WHERE id = ?", (issue_id,))
    conn.commit()
    conn.close()


def clear_all_quality_issues() -> int:
    """Mark all open quality issues as cleared. Returns count of issues cleared."""
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE quality_log SET cleared = 1 WHERE cleared IS NULL OR cleared = 0"
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def get_quality_summary() -> dict:
    """Return last check time and issue counts for the ops dashboard."""
    conn = get_connection()
    last_row = conn.execute(
        "SELECT checked_at FROM quality_log ORDER BY checked_at DESC LIMIT 1"
    ).fetchone()
    last_checked_at = last_row[0] if last_row else None

    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    counts = conn.execute(
        """SELECT port, severity, COUNT(*) as n
           FROM (
               SELECT DISTINCT check_type, severity, port, date, species, grade
               FROM quality_log WHERE checked_at >= ? AND (cleared IS NULL OR cleared = 0)
           )
           GROUP BY port, severity""",
        (cutoff,),
    ).fetchall()
    conn.close()

    by_port: dict[str, dict] = {}
    total_errors = 0
    total_warns = 0
    for port, severity, n in counts:
        by_port.setdefault(port, {"errors": 0, "warns": 0})
        if severity == "error":
            by_port[port]["errors"] += n
            total_errors += n
        else:
            by_port[port]["warns"] += n
            total_warns += n

    return {
        "last_checked_at": last_checked_at,
        "open_errors": total_errors,
        "open_warns": total_warns,
        "by_port": by_port,
    }


# ── Error log (error dashboard) ────────────────────────────────────────────


def insert_error_log(entries: list[dict]) -> None:
    """Insert new error_log rows. Each entry needs: check_name, severity, port, species, detail."""
    if not entries:
        return
    conn = get_connection()
    scanned_at = datetime.utcnow().isoformat()
    for e in entries:
        conn.execute(
            """INSERT INTO error_log (scanned_at, check_name, severity, port, species, detail, status)
               VALUES (?, ?, ?, ?, ?, ?, 'open')""",
            (scanned_at, e["check_name"], e["severity"], e.get("port"), e.get("species"), e.get("detail")),
        )
    conn.commit()
    conn.close()


def get_error_log(limit: int = 200) -> list[dict]:
    """Return open errors + recently resolved (last 48h), ordered by severity then recency."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cutoff_48h = (datetime.utcnow() - timedelta(hours=48)).isoformat()
    rows = conn.execute(
        """SELECT id, scanned_at, check_name, severity, port, species, detail,
                  status, resolved_at, resolution
           FROM error_log
           WHERE status = 'open'
              OR (status = 'resolved' AND resolved_at >= ?)
           ORDER BY
               CASE WHEN status = 'open' THEN 0 ELSE 1 END,
               CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
               scanned_at DESC
           LIMIT ?""",
        (cutoff_48h, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_error(error_id: int, resolution: str) -> None:
    """Mark an error as resolved with a resolution message."""
    conn = get_connection()
    conn.execute(
        "UPDATE error_log SET status = 'resolved', resolved_at = ?, resolution = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), resolution, error_id),
    )
    conn.commit()
    conn.close()


def get_last_scan_time() -> str | None:
    """Return the most recent scanned_at timestamp from error_log, or None."""
    conn = get_connection()
    row = conn.execute("SELECT MAX(scanned_at) FROM error_log").fetchone()
    conn.close()
    return row[0] if row else None


def clear_stale_errors(hours: int = 48) -> None:
    """Delete resolved errors older than `hours` hours. Keeps all open errors."""
    conn = get_connection()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    conn.execute(
        "DELETE FROM error_log WHERE status = 'resolved' AND resolved_at < ?",
        (cutoff,),
    )
    conn.commit()
    conn.close()
