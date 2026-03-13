"""Send the daily digest report via email.

Configuration via environment variables:
    QUAYSIDE_SMTP_HOST     SMTP server (default: smtp.gmail.com)
    QUAYSIDE_SMTP_PORT     SMTP port (default: 587)
    QUAYSIDE_SMTP_USER     SMTP username / sender email
    QUAYSIDE_SMTP_PASS     SMTP password or app password
    QUAYSIDE_RECIPIENTS    Comma-separated list of recipient emails

For Gmail, use an App Password (not your account password):
    https://myaccount.google.com/apppasswords
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_config() -> dict:
    """Read email config from environment variables."""
    user = os.environ.get("QUAYSIDE_SMTP_USER", "")
    password = os.environ.get("QUAYSIDE_SMTP_PASS", "")
    recipients = os.environ.get("QUAYSIDE_RECIPIENTS", "")

    if not user or not password or not recipients:
        raise ValueError(
            "Email not configured. Set QUAYSIDE_SMTP_USER, QUAYSIDE_SMTP_PASS, "
            "and QUAYSIDE_RECIPIENTS environment variables."
        )

    return {
        "host": os.environ.get("QUAYSIDE_SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("QUAYSIDE_SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "recipients": [r.strip() for r in recipients.split(",") if r.strip()],
    }


def send_digest(html_path: Path, date: str) -> None:
    """Send the digest HTML file as an email.

    Args:
        html_path: Path to the generated digest HTML file.
        date: The report date string (YYYY-MM-DD) for the subject line.
    """
    config = _get_config()

    html_content = html_path.read_text(encoding="utf-8")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Quayside Daily Digest — {date}"
    msg["From"] = config["user"]
    msg["To"] = ", ".join(config["recipients"])

    # Plain text fallback
    plain = (
        f"Quayside Daily Digest for {date}\n\n"
        "Your HTML email client is needed to view this report.\n"
        "Open the attached HTML file in a browser, or view online."
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP(config["host"], config["port"]) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config["user"], config["password"])
        server.sendmail(config["user"], config["recipients"], msg.as_string())

    logger.info(
        "Digest email sent to %d recipients for %s",
        len(config["recipients"]),
        date,
    )
