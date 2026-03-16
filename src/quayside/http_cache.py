"""HTTP ETag / Last-Modified / content-hash cache.

Avoids re-downloading unchanged files. Particularly useful for repeated
intraday pipeline runs — if the source PDF or HTML hasn't changed, we skip
parsing and DB writes entirely.

Cache stored at data/http_etag_cache.json:
    {
        "https://...": {
            "etag": "\"abc123\"",
            "last_modified": "Mon, 16 Mar 2026 10:00:00 GMT",
            "content_hash": "d41d8cd98f00b204e9800998ecf8427e"
        },
        ...
    }

Usage::

    from quayside.http_cache import cached_fetch

    content, is_new = cached_fetch(url, headers=SCRAPER_HEADERS)
    if not is_new:
        return []          # source unchanged — skip
    records = parse(content)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Locate cache file — respects QUAYSIDE_DATA_DIR env var for deployments
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DATA_DIR = Path(os.environ.get("QUAYSIDE_DATA_DIR", _DEFAULT_DATA_DIR))
CACHE_FILE = _DATA_DIR / "http_etag_cache.json"


def _load() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def cached_fetch(
    url: str,
    req_headers: dict | None = None,
) -> tuple[bytes | None, bool]:
    """Fetch a URL, skipping download if the content hasn't changed.

    Returns:
        (content, is_new) where:
            content  — bytes if fetched, None if unchanged
            is_new   — True if the content was actually downloaded/changed

    Raises:
        requests.RequestException on HTTP errors (not 304).

    The cache uses three complementary strategies (in priority order):
    1. ETag — server-side validation (most reliable)
    2. Last-Modified — time-based validation
    3. MD5 content hash — client-side fallback for servers that return neither
    """
    cache = _load()
    entry = cache.get(url, {})

    headers = dict(req_headers or {})
    if entry.get("etag"):
        headers["If-None-Match"] = entry["etag"]
    elif entry.get("last_modified"):
        headers["If-Modified-Since"] = entry["last_modified"]

    resp = requests.get(url, headers=headers, timeout=30)

    if resp.status_code == 304:
        logger.debug("ETag hit (304 Not Modified): %s", url)
        return None, False

    resp.raise_for_status()
    content = resp.content
    new_hash = hashlib.md5(content).hexdigest()

    # Build updated cache entry
    new_entry: dict = {"content_hash": new_hash}
    if resp.headers.get("ETag"):
        new_entry["etag"] = resp.headers["ETag"]
    if resp.headers.get("Last-Modified"):
        new_entry["last_modified"] = resp.headers["Last-Modified"]

    # Content-hash fallback: if server returned no ETag/Last-Modified headers
    # and the bytes haven't changed, treat as unchanged
    if (
        not new_entry.get("etag")
        and not new_entry.get("last_modified")
        and entry.get("content_hash") == new_hash
    ):
        logger.debug("Content-hash hit (unchanged): %s", url)
        cache[url] = new_entry
        _save(cache)
        return None, False

    cache[url] = new_entry
    _save(cache)
    logger.debug("Fetched (new/changed): %s", url)
    return content, True


def invalidate(url: str) -> None:
    """Remove a URL from the cache, forcing a full fetch next time."""
    cache = _load()
    if url in cache:
        del cache[url]
        _save(cache)
        logger.debug("Cache invalidated: %s", url)
