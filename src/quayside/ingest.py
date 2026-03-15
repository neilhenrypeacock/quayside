"""Email ingestion service — polls a mailbox for price data uploads.

Monitors a dedicated mailbox (e.g. prices@quayside.fish) for incoming
emails with file attachments. Identifies the sender's port, extracts
the attachment, routes it to the appropriate extractor, and creates
an upload record for HITL confirmation.

Configuration via environment variables:
    QUAYSIDE_INGEST_HOST      IMAP server (default: imap.gmail.com)
    QUAYSIDE_INGEST_PORT      IMAP port (default: 993)
    QUAYSIDE_INGEST_USER      IMAP username / email address
    QUAYSIDE_INGEST_PASS      IMAP password or app password
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from quayside.db import (
    create_upload,
    get_all_ports,
    upsert_prices_with_upload,
)
from quayside.extractors import extract_from_file

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"

# File extensions we accept as attachments
_ACCEPTED_EXTENSIONS = {
    ".xls", ".xlsx", ".csv", ".pdf",
    ".png", ".jpg", ".jpeg", ".heic", ".webp",
}


def _get_imap_config() -> dict:
    """Read IMAP config from environment variables."""
    user = os.environ.get("QUAYSIDE_INGEST_USER", "")
    password = os.environ.get("QUAYSIDE_INGEST_PASS", "")
    if not user or not password:
        raise ValueError(
            "Ingest not configured. Set QUAYSIDE_INGEST_USER and QUAYSIDE_INGEST_PASS."
        )
    return {
        "host": os.environ.get("QUAYSIDE_INGEST_HOST", "imap.gmail.com"),
        "port": int(os.environ.get("QUAYSIDE_INGEST_PORT", "993")),
        "user": user,
        "password": password,
    }


def _build_sender_map() -> dict[str, dict]:
    """Build a mapping of email address → port info from the ports table."""
    ports = get_all_ports()
    sender_map = {}
    for port in ports:
        if port.get("contact_email"):
            sender_map[port["contact_email"].lower()] = port
    return sender_map


def _identify_port(from_addr: str, sender_map: dict[str, dict]) -> dict | None:
    """Match a sender email to a port."""
    # Extract just the email address from "Name <email>" format
    match = re.search(r"<(.+?)>", from_addr)
    addr = match.group(1).lower() if match else from_addr.lower().strip()

    # Exact match
    if addr in sender_map:
        return sender_map[addr]

    # Domain match — if the email domain matches a port's contact domain
    domain = addr.split("@")[-1] if "@" in addr else ""
    for contact_email, port in sender_map.items():
        contact_domain = contact_email.split("@")[-1] if "@" in contact_email else ""
        if domain and domain == contact_domain:
            return port

    return None


def _save_attachment(msg_part, port_slug: str, date: str) -> Path | None:
    """Save an email attachment to the uploads directory. Returns the file path."""
    filename = msg_part.get_filename()
    if not filename:
        return None

    ext = Path(filename).suffix.lower()
    if ext not in _ACCEPTED_EXTENSIONS:
        logger.debug("Skipping attachment %s (unsupported extension)", filename)
        return None

    # Create port-specific upload directory
    port_dir = UPLOAD_DIR / port_slug / date
    port_dir.mkdir(parents=True, exist_ok=True)

    # Save with timestamp to avoid collisions
    ts = datetime.now().strftime("%H%M%S")
    safe_name = f"{ts}_{filename}"
    file_path = port_dir / safe_name
    file_path.write_bytes(msg_part.get_payload(decode=True))

    logger.info("Saved attachment: %s", file_path)
    return file_path


def process_email(raw_email: bytes, sender_map: dict[str, dict]) -> dict | None:
    """Process a single email message.

    Returns upload info dict on success, None if skipped.
    """
    msg = email.message_from_bytes(raw_email, policy=email.policy.default)
    from_addr = msg.get("From", "")
    subject = msg.get("Subject", "")
    date_str = datetime.now().strftime("%Y-%m-%d")

    logger.info("Processing email from %s: %s", from_addr, subject)

    # Identify the port
    port = _identify_port(from_addr, sender_map)
    if not port:
        logger.warning("Unknown sender: %s — skipping", from_addr)
        return None

    port_slug = port["slug"]
    port_name = port["name"]

    # Extract attachments
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            # Check if it's an inline image
            if part.get_content_type().startswith("image/"):
                pass  # Allow inline images
            else:
                continue

        file_path = _save_attachment(part, port_slug, date_str)
        if file_path:
            attachments.append(file_path)

    if not attachments:
        logger.warning("No valid attachments from %s (%s)", from_addr, port_name)
        return None

    # Process the first valid attachment (usually there's only one)
    file_path = attachments[0]
    records = extract_from_file(file_path, port_name, date_str)

    if not records:
        logger.warning("No prices extracted from %s for %s", file_path.name, port_name)
        return None

    # Create upload record
    upload_id = create_upload(
        port_slug=port_slug,
        date=date_str,
        method=f"email:{file_path.suffix.lstrip('.')}",
        raw_file_path=str(file_path),
        record_count=len(records),
    )

    # Store prices linked to this upload (pending confirmation)
    upsert_prices_with_upload(records, upload_id)

    logger.info(
        "Processed upload #%d: %d prices for %s from %s",
        upload_id, len(records), port_name, file_path.name,
    )

    return {
        "upload_id": upload_id,
        "port_slug": port_slug,
        "port_name": port_name,
        "date": date_str,
        "file": file_path.name,
        "record_count": len(records),
        "records": records,
    }


def poll_mailbox() -> list[dict]:
    """Poll the IMAP mailbox for new emails, process them.

    Returns list of upload info dicts for processed emails.
    """
    config = _get_imap_config()
    sender_map = _build_sender_map()

    results = []

    with imaplib.IMAP4_SSL(config["host"], config["port"]) as imap:
        imap.login(config["user"], config["password"])
        imap.select("INBOX")

        # Search for unread emails
        status, message_ids = imap.search(None, "UNSEEN")
        if status != "OK" or not message_ids[0]:
            logger.debug("No new emails")
            return results

        for msg_id in message_ids[0].split():
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            result = process_email(raw_email, sender_map)
            if result:
                results.append(result)
                # Mark as read (already done by fetching, but be explicit)
                imap.store(msg_id, "+FLAGS", "\\Seen")

    logger.info("Processed %d uploads from mailbox", len(results))
    return results
