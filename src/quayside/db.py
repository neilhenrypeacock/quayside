from __future__ import annotations

import sqlite3
from pathlib import Path

from quayside.models import LandingRecord, PriceRecord

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "quayside.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    conn = get_connection()
    conn.executescript("""
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
            UNIQUE(date, port, species, grade)
        );
    """)
    conn.close()


def upsert_landings(records: list[LandingRecord]) -> int:
    if not records:
        return 0
    conn = get_connection()
    conn.executemany(
        """INSERT OR REPLACE INTO landings
           (date, port, vessel_name, vessel_code, species, boxes, boxes_msc, scraped_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r.date,
                r.port,
                r.vessel_name,
                r.vessel_code,
                r.species,
                r.boxes,
                r.boxes_msc,
                r.scraped_at,
            )
            for r in records
        ],
    )
    conn.commit()
    count = len(records)
    conn.close()
    return count


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


def get_landings_by_date(date: str, port: str) -> list[tuple]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT date, port, vessel_name, vessel_code, species, boxes, boxes_msc
           FROM landings WHERE date = ? AND port = ?
           ORDER BY vessel_name, species""",
        (date, port),
    ).fetchall()
    conn.close()
    return rows


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


def get_all_prices_for_date(date: str) -> list[tuple]:
    """All price rows for a given date, across all ports."""
    conn = get_connection()
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


def get_previous_date(date: str) -> str | None:
    """Most recent date before the given date (for day-over-day comparison)."""
    conn = get_connection()
    row = conn.execute("SELECT MAX(date) FROM prices WHERE date < ?", (date,)).fetchone()
    conn.close()
    return row[0] if row else None
