"""Email transport for verification and password reset messages.

Console mode is the default local workflow. SMTP mode is used when the app is
put behind HTTPS and needs to send real verification or reset links.
"""

from __future__ import annotations

import asyncio
import os
import smtplib
from email.message import EmailMessage


async def send_auth_email(to_email: str, subject: str, body: str) -> None:
    mode = os.getenv("FINEDGAR_EMAIL_MODE", "console").lower()
    if mode == "smtp":
        await asyncio.to_thread(_send_smtp, to_email, subject, body)
        return

    print("\n=== FinEdgar auth email ===", flush=True)
    print(f"To: {to_email}", flush=True)
    print(f"Subject: {subject}", flush=True)
    print(body, flush=True)
    print("=== end auth email ===\n", flush=True)


def _send_smtp(to_email: str, subject: str, body: str) -> None:
    host = os.environ["FINEDGAR_SMTP_HOST"]
    port = int(os.getenv("FINEDGAR_SMTP_PORT", "587"))
    username = os.getenv("FINEDGAR_SMTP_USERNAME")
    password = os.getenv("FINEDGAR_SMTP_PASSWORD")
    use_tls = os.getenv("FINEDGAR_SMTP_STARTTLS", "1").lower() not in {"0", "false", "no"}
    sender = os.getenv("FINEDGAR_EMAIL_FROM", username or "noreply@localhost")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
