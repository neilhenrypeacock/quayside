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
    # Current scraped ports
    ("peterhead", "Peterhead", "PTH", "NE Scotland", "scraper", "active"),
    ("lerwick", "Lerwick", "LWK", "Shetland", "scraper", "active"),
    ("brixham", "Brixham", "BRX", "SW England", "scraper", "active"),
    ("newlyn", "Newlyn", "NLN", "SW England", "scraper", "active"),
    ("scrabster", "Scrabster", "SCR", "N Highlands", "scraper", "active"),
    # Upload ports — onboarding targets
    ("fraserburgh", "Fraserburgh", "FRB", "NE Scotland", "upload", "onboarding"),
    ("kinlochbervie", "Kinlochbervie", "KLB", "NW Highlands", "upload", "onboarding"),
    ("macduff", "Macduff", "MCD", "NE Scotland", "upload", "inactive"),
    ("milford-haven", "Milford Haven", "MLF", "Wales", "upload", "inactive"),
    ("grimsby", "Grimsby", "GRM", "E England", "upload", "inactive"),
    ("lowestoft", "Lowestoft", "LOW", "E England", "upload", "inactive"),
    ("eyemouth", "Eyemouth", "EYE", "SE Scotland", "upload", "inactive"),
    ("whitby", "Whitby", "WHT", "NE England", "upload", "inactive"),
    ("fleetwood", "Fleetwood", "FLW", "NW England", "upload", "inactive"),
    ("kilkeel", "Kilkeel", "KIL", "N. Ireland", "upload", "inactive"),
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
