"""Document extractors — turn uploaded files into PriceRecord lists.

Each extractor takes a file path and port name, returns list[PriceRecord].
"""

from __future__ import annotations

import logging
from pathlib import Path

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)


def extract_from_file(file_path: Path, port: str, date: str) -> list[PriceRecord]:
    """Route a file to the appropriate extractor based on extension.

    Returns list of PriceRecords. Falls back to AI extraction for unknown formats.
    """
    suffix = file_path.suffix.lower()

    if suffix in (".xls", ".xlsx"):
        from quayside.extractors.xls import extract_prices
        return extract_prices(file_path, port, date)
    elif suffix == ".csv":
        from quayside.extractors.csv_ext import extract_prices
        return extract_prices(file_path, port, date)
    elif suffix == ".pdf":
        from quayside.extractors.pdf import extract_prices
        return extract_prices(file_path, port, date)
    elif suffix in (".png", ".jpg", ".jpeg", ".heic", ".webp"):
        from quayside.extractors.image import extract_prices
        return extract_prices(file_path, port, date)
    else:
        logger.warning("Unknown file type %s — trying AI extraction", suffix)
        from quayside.extractors.ai import extract_prices
        return extract_prices(file_path, port, date)
