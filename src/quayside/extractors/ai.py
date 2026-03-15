"""AI-powered extraction fallback for unknown document formats.

Uses Claude API to extract structured price data from any text content.
This is the last-resort extractor when deterministic parsers fail.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Extract fish species prices from this document text. This is a price sheet from a UK fish auction port called "{port}".

Return a JSON array of objects, each with these fields:
- "species": the fish species name (exactly as written in the document)
- "grade": the grade/quality if shown (e.g. "A1", "1", etc.), or "" if not shown
- "price_low": the lowest price in GBP per kg (as a number), or null if not shown
- "price_high": the highest price in GBP per kg (as a number), or null if not shown
- "price_avg": the average price in GBP per kg (as a number), or null if not shown

Important:
- Extract ALL species and price rows
- If only one price is shown per species, put it in price_avg
- If prices are in pence, convert to pounds (e.g. 271p = 2.71)
- Return ONLY the JSON array, no other text

Document text:
{text}"""


def extract_prices(file_path: Path, port: str, date: str) -> list[PriceRecord]:
    """Extract price records from any file by reading its text and using Claude API."""
    text = _extract_text(file_path)
    if not text.strip():
        logger.warning("No text extracted from %s", file_path)
        return []

    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": _EXTRACTION_PROMPT.format(port=port, text=text[:8000]),
        }],
    )

    response_text = response.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        items = json.loads(response_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse AI extraction response for %s", port)
        return []

    records = []
    now = datetime.now().isoformat()
    for item in items:
        species = str(item.get("species", "")).strip()
        if not species:
            continue

        avg = item.get("price_avg")
        low = item.get("price_low")
        high = item.get("price_high")

        if avg is None and low is not None and high is not None:
            avg = round((low + high) / 2, 2)
        if avg is None and low is None and high is None:
            continue

        records.append(PriceRecord(
            date=date, port=port, species=species,
            grade=str(item.get("grade", "")).strip(),
            price_low=low, price_high=high, price_avg=avg,
            scraped_at=now,
        ))

    logger.info("Extracted %d prices via AI for %s", len(records), port)
    return records


def _extract_text(file_path: Path) -> str:
    """Extract text content from a file."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        import pdfplumber
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)

    elif suffix in (".xls", ".xlsx"):
        if suffix == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            ws = wb.active
            lines = []
            for row in ws.iter_rows(values_only=True):
                lines.append("\t".join(str(c) if c is not None else "" for c in row))
            wb.close()
            return "\n".join(lines)
        else:
            import xlrd
            wb = xlrd.open_workbook(str(file_path))
            ws = wb.sheet_by_index(0)
            lines = []
            for row_idx in range(ws.nrows):
                cells = [str(ws.cell_value(row_idx, c)) for c in range(ws.ncols)]
                lines.append("\t".join(cells))
            return "\n".join(lines)

    else:
        # Try reading as plain text
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="latin-1")
