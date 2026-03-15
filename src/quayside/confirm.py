"""Confirmation system — HITL email flow for uploaded price data.

After extraction, sends a confirmation email to the port contact with:
- A table of extracted prices
- A "Looks good" link (confirms immediately)
- A "Fix something" link (opens editable web table)

Also handles auto-publishing uploads that go unconfirmed after 2 hours.
"""

from __future__ import annotations

import logging
import os
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from quayside.db import (
    auto_publish_upload,
    get_pending_uploads,
    get_port,
    get_upload,
)
from quayside.models import PriceRecord

logger = logging.getLogger(__name__)

# Confirmation tokens: {token: upload_id}
# In production, store in DB. For now, in-memory is fine for a single-process app.
_confirm_tokens: dict[str, int] = {}


def generate_confirm_token(upload_id: int) -> str:
    """Generate a unique confirmation token for an upload."""
    token = secrets.token_urlsafe(32)
    _confirm_tokens[token] = upload_id
    return token


def get_upload_for_token(token: str) -> int | None:
    """Look up the upload_id for a confirmation token."""
    return _confirm_tokens.get(token)


def send_confirmation_email(
    upload_id: int,
    records: list[PriceRecord],
    base_url: str = "",
) -> None:
    """Send a confirmation email to the port contact.

    Args:
        upload_id: The upload record ID.
        records: Extracted price records to confirm.
        base_url: Base URL for confirmation links (e.g. https://quayside.fish).
    """
    upload = get_upload(upload_id)
    if not upload:
        logger.error("Upload %d not found", upload_id)
        return

    port = get_port(upload["port_slug"])
    if not port or not port.get("contact_email"):
        logger.warning("No contact email for port %s", upload["port_slug"])
        return

    # Generate confirmation token
    confirm_token = generate_confirm_token(upload_id)

    if not base_url:
        base_url = os.environ.get("QUAYSIDE_BASE_URL", "http://localhost:5000")

    confirm_url = f"{base_url}/confirm/{confirm_token}"
    correct_url = f"{base_url}/confirm/{confirm_token}/edit"

    # Build the email
    port_name = port["name"]
    date = upload["date"]
    count = len(records)

    # Build price table rows
    table_rows = ""
    for r in sorted(records, key=lambda x: x.species):
        low = f"£{r.price_low:.2f}" if r.price_low else "—"
        high = f"£{r.price_high:.2f}" if r.price_high else "—"
        avg = f"£{r.price_avg:.2f}" if r.price_avg else "—"
        table_rows += f"""
            <tr>
                <td style="padding:6px 12px;border-bottom:1px solid #e0ddd5;">{r.species}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #e0ddd5;">{r.grade}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #e0ddd5;text-align:right;">{low}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #e0ddd5;text-align:right;">{high}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #e0ddd5;text-align:right;font-weight:600;">{avg}</td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:0;padding:20px;background:#f5f0e8;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <div style="background:#1a3a4a;padding:20px 24px;color:#fff;">
        <h2 style="margin:0;font-size:18px;">{port_name} prices — {date}</h2>
        <p style="margin:4px 0 0;opacity:0.8;font-size:14px;">{count} species extracted</p>
    </div>

    <div style="padding:20px 24px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <thead>
                <tr style="background:#f5f0e8;">
                    <th style="padding:8px 12px;text-align:left;font-weight:600;">Species</th>
                    <th style="padding:8px 12px;text-align:left;font-weight:600;">Grade</th>
                    <th style="padding:8px 12px;text-align:right;font-weight:600;">Low</th>
                    <th style="padding:8px 12px;text-align:right;font-weight:600;">High</th>
                    <th style="padding:8px 12px;text-align:right;font-weight:600;">Avg</th>
                </tr>
            </thead>
            <tbody>{table_rows}
            </tbody>
        </table>
    </div>

    <div style="padding:20px 24px;text-align:center;border-top:1px solid #e0ddd5;">
        <a href="{confirm_url}" style="display:inline-block;background:#2d7a4f;color:#fff;padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;margin-right:12px;">
            ✓ Looks good
        </a>
        <a href="{correct_url}" style="display:inline-block;background:#f5f0e8;color:#1a3a4a;padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;border:1px solid #d0cdc5;">
            ✏ Fix something
        </a>
    </div>

    <div style="padding:12px 24px;font-size:12px;color:#888;text-align:center;">
        If we don't hear back within 2 hours, we'll publish this data as-is.
    </div>

</div>
</body>
</html>"""

    # Send via SMTP (reuse digest email config)
    smtp_user = os.environ.get("QUAYSIDE_SMTP_USER", "")
    smtp_pass = os.environ.get("QUAYSIDE_SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
        logger.warning("SMTP not configured — skipping confirmation email for upload %d", upload_id)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Confirm: {port_name} prices — {date}"
    msg["From"] = smtp_user
    msg["To"] = port["contact_email"]

    plain = (
        f"{port_name} prices for {date}\n"
        f"{count} species extracted.\n\n"
        f"Confirm: {confirm_url}\n"
        f"Fix: {correct_url}\n"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    host = os.environ.get("QUAYSIDE_SMTP_HOST", "smtp.gmail.com")
    port_num = int(os.environ.get("QUAYSIDE_SMTP_PORT", "587"))

    with smtplib.SMTP(host, port_num) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [port["contact_email"]], msg.as_string())

    logger.info("Confirmation email sent to %s for upload %d", port["contact_email"], upload_id)


def auto_publish_stale_uploads(timeout_hours: int = 2) -> int:
    """Auto-publish any uploads still pending past the timeout.

    Returns the number of uploads auto-published.
    """
    pending = get_pending_uploads(older_than_hours=timeout_hours)
    count = 0
    for upload in pending:
        auto_publish_upload(upload["id"])
        logger.info(
            "Auto-published upload %d for %s (no confirmation after %dh)",
            upload["id"], upload["port_slug"], timeout_hours,
        )
        count += 1
    return count
