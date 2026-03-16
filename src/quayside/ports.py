"""Port registry — canonical list of all UK fish ports.

Replaces the hardcoded PORT_CODES dict in report.py with a database-backed
registry. On first run, seeds the ports table with all known ports.
"""

from __future__ import annotations

import logging

from quayside.db import get_all_ports, get_port_codes, upsert_port

logger = logging.getLogger(__name__)

# Master list: (slug, name, code, region, data_method, status)
_SEED_PORTS = [
    # ── Demo port — populated with synthetic data for showcasing ──
    ("demo", "Demo Port", "DEM", "Scotland — North East", "demo", "active"),
    # ── Live ports ──
    # Scotland — North & Islands
    ("lerwick", "Lerwick", "LWK", "Scotland — North & Islands", "scraper", "active"),
    ("scrabster", "Scrabster", "SCR", "Scotland — North & Islands", "scraper", "active"),
    # Scotland — North East
    ("peterhead", "Peterhead", "PTH", "Scotland — North East", "scraper", "active"),
    # England — South West
    ("brixham", "Brixham", "BRX", "England — South West", "scraper", "active"),
    ("newlyn", "Newlyn", "NLN", "England — South West", "scraper", "active"),
    # ── Pipeline: priority outreach ──
    # Scotland — priority targets (biggest ports after Peterhead)
    ("fraserburgh", "Fraserburgh", "FRB", "Scotland — North East", "upload", "outreach"),
    ("kinlochbervie", "Kinlochbervie", "KLB", "Scotland — North & Islands", "upload", "outreach"),
    ("macduff", "Macduff", "MCD", "Scotland — North East", "upload", "outreach"),
    ("eyemouth", "Eyemouth", "EYE", "Scotland — South East", "upload", "outreach"),
    # England — priority targets
    ("grimsby", "Grimsby", "GRM", "England — East", "upload", "outreach"),
    ("fleetwood", "Fleetwood", "FLW", "England — North West", "upload", "outreach"),
    # ── Future ──
    ("lowestoft", "Lowestoft", "LOW", "England — East", "upload", "future"),
    ("whitby", "Whitby", "WHT", "England — North East", "upload", "future"),
    ("milford-haven", "Milford Haven", "MLF", "Wales", "upload", "future"),
    ("kilkeel", "Kilkeel", "KIL", "Northern Ireland", "upload", "future"),
]


def seed_ports() -> None:
    """Seed the ports table with the master list (idempotent)."""
    for slug, name, code, region, method, status in _SEED_PORTS:
        upsert_port(
            slug=slug, name=name, code=code, region=region,
            data_method=method, status=status,
        )
    logger.info("Seeded %d ports", len(_SEED_PORTS))


def get_port_code_map() -> dict[str, str]:
    """Return {port_name: port_code} for all ports.

    Falls back to the seed data if the ports table is empty (e.g. before first run).
    """
    codes = get_port_codes()
    if codes:
        return codes
    # Fallback: return from seed data
    return {name: code for _, name, code, _, _, _ in _SEED_PORTS}


def get_active_port_names() -> list[str]:
    """Return names of all active ports."""
    ports = get_all_ports(status="active")
    return [p["name"] for p in ports]


def get_upload_ports() -> list[dict]:
    """Return ports that use the upload method."""
    all_ports = get_all_ports()
    return [p for p in all_ports if p["data_method"] == "upload"]
