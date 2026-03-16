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
    existing_landings = {row[1] for row in conn.execute("PRAGMA table_info(landings)").fetchall()}
    if existing_landings and "scraped_at" not in existing_landings:
        conn.execute("ALTER TABLE landings ADD COLUMN scraped_at TEXT NOT NULL DEFAULT ''")
    conn.commit()


def upsert_prices(records: list[PriceRecord]) -> int:
    if not records:
        return 0
    conn = get_connection()
    conn.executemany(
        """INSERT OR REPLACE INTO prices
           (date, port, species, grade, price_low, price_high, price_avg, scraped_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r.date,
                r.port,
                r.species,
                r.grade,
                r.price_low,
                r.price_high,
                r.price_avg,
                r.scraped_at,
            )
            for r in records
        ],
    )
    conn.commit()
    count = len(records)
    conn.close()
    return count


def get_prices_by_date(date: str, port: str) -> list[tuple]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT date, port, species, grade, price_low, price_high, price_avg
           FROM prices WHERE date = ? AND port = ?
           ORDER BY species, grade""",
        (date, port),
    ).fetchall()
    conn.close()
    return rows


def get_all_prices_for_date(date: str, exclude_demo: bool = False) -> list[tuple]:
    """All price rows for a given date, across all ports."""
    conn = get_connection()
    if exclude_demo:
        rows = conn.execute(
            """SELECT p.date, p.port, p.species, p.grade, p.price_low, p.price_high, p.price_avg
               FROM prices p
               LEFT JOIN ports po ON po.name = p.port
               WHERE p.date = ? AND (po.data_method IS NULL OR po.data_method != 'demo')
               ORDER BY p.species, p.port, p.grade""",
            (date,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT date, port, species, grade, price_low, price_high, price_avg
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


def get_port_auction_dates(port: str, limit: int = 20) -> list[str]:
    """Most recent auction dates for a specific port, newest first."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT DISTINCT date FROM prices
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
    conn.executemany(
        """INSERT OR REPLACE INTO prices
           (date, port, species, grade, price_low, price_high, price_avg, scraped_at, upload_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r.date, r.port, r.species, r.grade,
                r.price_low, r.price_high, r.price_avg, r.scraped_at, upload_id,
            )
            for r in records
        ],
    )
    conn.commit()
    count = len(records)
    conn.close()
    return count


# --- Dashboard queries ---


def get_port_prices_history(port: str, days: int = 30) -> list[tuple]:
    """Price history for a single port over the last N days."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT date, species, grade, price_low, price_high, price_avg
           FROM prices
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
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(scraped_at) FROM prices WHERE port = ? AND date = ?",
        (port, date),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def seed_demo_port_data() -> None:
    """Seed 30 days of realistic price data for the Demo Port.

    Always runs — refreshes demo data so the dashboard always looks current.
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
    records: list[PriceRecord] = []

    for day_offset in range(30):
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
                records.append(PriceRecord(
                    date=date_str,
                    port=PORT_NAME,
                    species=species_name,
                    grade=grade,
                    price_low=round(price_avg - spread, 2),
                    price_high=round(price_avg + spread, 2),
                    price_avg=price_avg,
                    scraped_at=date.isoformat(),
                ))

    upsert_prices(records)


def get_prices_by_date_for_port(date: str, port: str) -> list[tuple]:
    """Price rows for a specific port on a specific date (same as get_prices_by_date)."""
    return get_prices_by_date(date, port)


def get_same_day_last_week(port: str, date: str) -> dict[str, dict]:
    """Get prices for the same weekday one week ago for a port.

    Returns {(species, grade): {price_avg, price_low, price_high}}.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT species, grade, price_low, price_high, price_avg
           FROM prices
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
    conn = get_connection()
    rows = conn.execute(
        """SELECT DISTINCT species FROM prices
           WHERE port = ?
             AND date > date(?, '-30 days')
             AND date <= date(?, '-5 days')
             AND species NOT IN (
                 SELECT DISTINCT species FROM prices
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
    conn = get_connection()
    rows = conn.execute(
        """SELECT species, AVG(price_avg) as avg_price
           FROM prices
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
