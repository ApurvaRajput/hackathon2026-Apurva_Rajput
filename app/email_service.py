"""
email_service.py — ShopWave Email Notification Service
=======================================================

Purpose:
    Provides the send_email() function used to notify customers via email
    whenever a support ticket is resolved by the AI agent.

Role in System:
    Called by agent.py (inside send_and_remember) immediately after a reply
    is successfully sent via send_reply(). Email delivery failure is caught
    and logged, but never raises — it must never crash the main agent loop.

Configuration (environment variables):
    EMAIL_HOST      — SMTP server hostname  (default: smtp.gmail.com)
    EMAIL_PORT      — SMTP server port      (default: 587)
    EMAIL_USER      — Sender email address
    EMAIL_PASSWORD  — Sender account password / app-password

Example usage:
    >>> from app.email_service import send_email
    >>> result = send_email(
    ...     to_email="customer@example.com",
    ...     subject="Your Support Ticket Has Been Resolved",
    ...     body="Hi Alice, your refund has been processed …",
    ... )
    >>> print(result)
    {'status': 'success', 'message': 'Email delivered to customer@example.com'}
"""

from __future__ import annotations

import os
import re
import smtplib
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

# ── SMTP constants (overridable via env) ──────────────────────────────────────
_DEFAULT_HOST = "smtp.gmail.com"
_DEFAULT_PORT = 587
_CONNECT_TIMEOUT = 10  # seconds — prevents hanging on unreachable hosts

# ── HTML Email Template ───────────────────────────────────────────────────────
_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
            background-color: #f3f4f6; 
            color: #1f2937; 
            margin: 0; 
            padding: 0; 
            -webkit-font-smoothing: antialiased;
        }
        .container { 
            max-width: 600px; 
            margin: 40px auto; 
            background: #ffffff; 
            border-radius: 12px; 
            overflow: hidden; 
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05); 
        }
        .header { 
            background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%); 
            padding: 32px 40px; 
            text-align: center; 
        }
        .header h1 { 
            color: #ffffff; 
            margin: 0; 
            font-size: 28px; 
            font-weight: 700; 
            letter-spacing: -0.025em; 
        }
        .content { 
            padding: 40px; 
            line-height: 1.6; 
            font-size: 16px; 
        }
        .footer { 
            background-color: #f9fafb; 
            padding: 24px 40px; 
            text-align: center; 
            font-size: 14px; 
            color: #6b7280; 
            border-top: 1px solid #e5e7eb; 
        }
        .status-badge { 
            display: inline-block; 
            background-color: #10b981; 
            color: white; 
            padding: 6px 14px; 
            border-radius: 9999px; 
            font-size: 14px; 
            font-weight: 600; 
            margin-bottom: 24px; 
            box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        }
        .message-box { 
            background-color: #f8fafc; 
            border-left: 4px solid #3b82f6; 
            padding: 24px; 
            margin: 8px 0; 
            border-radius: 0 8px 8px 0; 
            color: #334155; 
            white-space: pre-wrap; 
            font-size: 15px;
        }
        .message-box p {
            margin-top: 0;
        }
        .message-box p:last-child {
            margin-bottom: 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>ShopWave Support</h1>
        </div>
        <div class="content">
            <div class="status-badge">✓ Ticket Resolved</div>
            <div class="message-box">{body_html}</div>
        </div>
        <div class="footer">
            <p>Thank you for shopping with ShopWave.</p>
            <p>If you have any further questions, simply reply to this email.</p>
        </div>
    </div>
</body>
</html>
"""


# ── Regex for basic email validation ─────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_valid_email(address: str) -> bool:
    """Return True when *address* looks like a plausible email address.

    Parameters
    ----------
    address : str
        The email address to validate.

    Returns
    -------
    bool
        True if the format is valid, False otherwise.
    """
    return bool(_EMAIL_RE.match(address.strip()))


def _load_credentials() -> tuple[str, int, str, str]:
    """Read SMTP credentials from environment variables.

    Returns
    -------
    tuple[str, int, str, str]
        (host, port, user, password) — all as strings except port (int).

    Raises
    ------
    RuntimeError
        If EMAIL_USER or EMAIL_PASSWORD are not set.
    """
    host = os.getenv("EMAIL_HOST", _DEFAULT_HOST)

    # Convert port with a safe fallback to the default value
    try:
        port = int(os.getenv("EMAIL_PORT", str(_DEFAULT_PORT)))
    except ValueError:
        port = _DEFAULT_PORT

    user = os.getenv("EMAIL_USER", "")
    password = os.getenv("EMAIL_PASSWORD", "")

    if not user or not password:
        raise RuntimeError(
            "EMAIL_USER and EMAIL_PASSWORD environment variables must be set."
        )

    return host, port, user, password


def send_email(to_email: str, subject: str, body: str) -> dict[str, Any]:
    """Send a plain-text email via SMTP with STARTTLS.

    The function validates the recipient address, loads SMTP credentials from
    environment variables, connects with a timeout, upgrades to TLS, and
    delivers the message.  All failure modes are caught and returned as a
    structured error dict so callers can log without crashing.

    Parameters
    ----------
    to_email : str
        Recipient email address.
    subject : str
        Email subject line.
    body : str
        Plain-text email body.

    Returns
    -------
    dict
        On success::

            {"status": "success", "message": "Email delivered to <to_email>"}

        On failure::

            {"status": "error", "message": "<reason>"}

    Example usage
    -------------
    >>> result = send_email(
    ...     to_email="alice@example.com",
    ...     subject="Your Support Ticket Has Been Resolved",
    ...     body="Hi Alice, your refund has been processed.",
    ... )
    >>> assert result["status"] == "success"
    """
    # ── 1. Validate recipient address early to avoid an SMTP round-trip ───────
    if not _is_valid_email(to_email):
        return {
            "status": "error",
            "message": f"Invalid email address: '{to_email}'",
        }

    # ── 2. Load and validate credentials ─────────────────────────────────────
    try:
        host, port, user, password = _load_credentials()
    except RuntimeError as exc:
        # Missing credentials — log details and bail out gracefully
        return {"status": "error", "message": str(exc)}

    # ── 3. Build the MIME message ─────────────────────────────────────────────
    msg = MIMEMultipart("alternative")
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject

    # Attach as plain text
    msg.attach(MIMEText(body, "plain"))

    # Prepare and attach HTML version
    import html
    escaped_body = html.escape(body)
    # Convert double newlines to paragraphs, single newlines to <br> for simple HTML formatting
    html_body_content = escaped_body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    if not html_body_content.startswith("<p>"):
        html_body_content = f"<p>{html_body_content}</p>"

    html_content = _HTML_TEMPLATE.replace("{body_html}", html_body_content)
    msg.attach(MIMEText(html_content, "html"))

    # ── 4. Connect, upgrade to TLS, authenticate, and send ───────────────────
    try:
        # socket.create_connection respects _CONNECT_TIMEOUT to avoid
        # hanging forever when the SMTP host is unreachable.
        with smtplib.SMTP(host, port, timeout=_CONNECT_TIMEOUT) as server:
            server.ehlo()                  # introduce ourselves to the server
            server.starttls()              # upgrade plain socket → TLS
            server.ehlo()                  # re-introduce after TLS handshake
            server.login(user, password)   # authenticate
            server.sendmail(user, to_email, msg.as_string())

        return {
            "status": "success",
            "message": f"Email delivered to {to_email}",
        }

    # ── Granular error handling so log messages are actionable ───────────────
    except smtplib.SMTPAuthenticationError:
        return {
            "status": "error",
            "message": "SMTP authentication failed. Check EMAIL_USER and EMAIL_PASSWORD.",
        }
    except smtplib.SMTPRecipientsRefused:
        return {
            "status": "error",
            "message": f"SMTP server rejected recipient: {to_email}",
        }
    except smtplib.SMTPException as exc:
        return {
            "status": "error",
            "message": f"SMTP error: {exc}",
        }
    except (socket.timeout, TimeoutError):
        # Raised when the TCP connection to the SMTP host times out
        return {
            "status": "error",
            "message": f"Connection to SMTP host '{host}:{port}' timed out after {_CONNECT_TIMEOUT}s.",
        }
    except OSError as exc:
        # Covers DNS failures, connection refused, and other network errors
        return {
            "status": "error",
            "message": f"Network error while connecting to SMTP: {exc}",
        }
