"""Security helpers for local accounts and same-origin authenticated requests.

Passwords use Argon2id through `pwdlib`. Session and email tokens are opaque in
the browser and stored as keyed hashes in Postgres. Unsafe authenticated
requests are checked against the request origin, the configured public base URL,
and any explicitly allowed origins.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status
from pwdlib import PasswordHash

SESSION_COOKIE = "finedgar_session"
_password_hash = PasswordHash.recommended()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    pepper = os.getenv("FINEDGAR_AUTH_SECRET", "")
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def session_ttl() -> timedelta:
    days = int(os.getenv("FINEDGAR_SESSION_DAYS", "7"))
    return timedelta(days=max(days, 1))


def verification_ttl() -> timedelta:
    hours = int(os.getenv("FINEDGAR_EMAIL_TOKEN_HOURS", "24"))
    return timedelta(hours=max(hours, 1))


def reset_ttl() -> timedelta:
    minutes = int(os.getenv("FINEDGAR_PASSWORD_RESET_MINUTES", "60"))
    return timedelta(minutes=max(minutes, 5))


def cookie_secure() -> bool:
    return os.getenv("FINEDGAR_AUTH_COOKIE_SECURE", "1").lower() not in {"0", "false", "no"}


def public_base_url() -> str:
    return os.getenv("FINEDGAR_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return None


def validate_same_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    candidate = origin or referer
    if not candidate:
        return

    host = request.headers.get("host", "")
    parsed = urlparse(candidate)
    candidate_host = parsed.netloc
    allowed = {host}
    configured = os.getenv("FINEDGAR_ALLOWED_ORIGINS", os.getenv("FINEDGAR_ALLOW_ORIGINS", ""))
    for value in configured.split(","):
        value = value.strip()
        if not value:
            continue
        allowed.add(urlparse(value).netloc or value)
    allowed.add(urlparse(public_base_url()).netloc)
    if candidate_host not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cross-origin authenticated request rejected",
        )
