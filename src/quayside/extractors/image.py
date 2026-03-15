"""Extract prices from images using Claude Vision API.

Handles photos of whiteboards, printed price sheets, handwritten logs, etc.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from pathlib import Path

from quayside.models import PriceRecord

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Extract fish species prices from this image. This is a price sheet from a UK fish auction port.

Return a JSON array of objects, each with these fields:
- "species": the fish species name (exactly as written)
- "grade": the grade/quality if shown (e.g. "A1", "1", etc.), or "" if not shown
- "price_low": the lowest price in GBP per kg (as a number), or null if not shown
- "price_high": the highest price in GBP per kg (as a number), or null if not shown
- "price_avg": the average price in GBP per kg (as a number), or null if not shown

Important:
- Extract ALL species and rows, even if some prices are missing
- If only one price is shown per species, put it in price_avg
- If prices are in pence, convert to pounds (e.g. 271p = 2.71)
- Return ONLY the JSON array, no other text

Example output:
[{"species": "Haddock", "grade": "A1", "price_low": 2.41, "price_high": 2.89, "price_avg": 2.71}]"""


def extract_prices(file_path: Path, port: str, date: str) -> list[PriceRecord]:
    """Extract price records from an image file using Claude Vision."""
    import anthropic

    client = anthropic.Anthropic()

    # Read and encode image
    image_data = file_path.read_bytes()
    base64_image = base64.b64encode(image_data).decode("utf-8")

    # Detect media type
    suffix = file_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".heic": "image/heic",
    }
    media_type = media_types.get(suffix, "image/jpeg")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_image,
                    },
                },
                {
                    "type": "text",
                    "text": _EXTRACTION_PROMPT,
                },
            ],
        }],
    )

    # Parse the JSON response
    response_text = response.content[0].text.strip()
    # Handle markdown code blocks
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        items = json.loads(response_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Claude Vision response as JSON for %s", port)
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

    logger.info("Extracted %d prices from image for %s (Claude Vision)", len(records), port)
    return records
