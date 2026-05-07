"""Authentication service layer.

This module owns account creation, email verification, login/logout, password
reset, current-user lookup, and auth event recording. Routes should keep auth
business rules here so cookie, token, and database behavior stays consistent.
"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..db_models import (
    AuthEvent,
    EmailVerificationToken,
    PasswordResetToken,
    Session as DbSession,
    User,
    utcnow,
)
from ..emailer import send_auth_email
from ..schemas import UserPublic
from ..security import (
    SESSION_COOKIE,
    client_ip,
    cookie_secure,
    hash_password,
    hash_token,
    new_token,
    normalize_email,
    now_utc,
    public_base_url,
    reset_ttl,
    session_ttl,
    validate_same_origin,
    verification_ttl,
    verify_password,
)


def user_public(user: User) -> UserPublic:
    return UserPublic(id=user.id, email=user.email, is_verified=user.is_verified)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=now_utc().tzinfo)
    return dt


async def record_event(
    db: AsyncSession,
    request: Request,
    event_type: str,
    *,
    user: User | None = None,
    email: str | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuthEvent(
            user_id=user.id if user else None,
            email=email or (user.email if user else None),
            event_type=event_type,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            detail=detail,
        )
    )


async def create_user(db: AsyncSession, request: Request, email: str, password: str) -> User:
    email_norm = normalize_email(email)
    existing = await db.scalar(select(User).where(User.email == email_norm))
    if existing:
        await record_event(db, request, "register_duplicate", email=email_norm)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")

    user = User(email=email_norm, password_hash=hash_password(password))
    db.add(user)
    await db.flush()
    await send_verification(db, user)
    await record_event(db, request, "register", user=user)
    await db.commit()
    await db.refresh(user)
    return user


async def send_verification(db: AsyncSession, user: User) -> str:
    token = new_token()
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now_utc() + verification_ttl(),
        )
    )
    verify_url = f"{public_base_url()}/verify-email?token={token}"
    await send_auth_email(
        user.email,
        "Verify your FinEdgar account",
        f"Open this link to verify your FinEdgar account:\n\n{verify_url}\n\nThis link expires soon.",
    )
    return token


async def verify_email_token(db: AsyncSession, request: Request, token: str) -> User:
    token_row = await db.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == hash_token(token))
    )
    if not token_row or token_row.used_at is not None or _aware(token_row.expires_at) < now_utc():
        await record_event(db, request, "verify_email_failed")
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired verification token")

    user = await db.get(User, token_row.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid verification token")
    token_row.used_at = now_utc()
    user.is_verified = True
    await record_event(db, request, "verify_email", user=user)
    await db.commit()
    await db.refresh(user)
    return user


async def login_user(db: AsyncSession, request: Request, response: Response, email: str, password: str) -> User:
    email_norm = normalize_email(email)
    user = await db.scalar(select(User).where(User.email == email_norm))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        await record_event(db, request, "login_failed", email=email_norm)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    if not user.is_verified:
        await record_event(db, request, "login_unverified", user=user)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email verification required")

    token = new_token()
    expires_at = now_utc() + session_ttl()
    db.add(
        DbSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
            user_agent=request.headers.get("user-agent"),
            ip_address=client_ip(request),
        )
    )
    await record_event(db, request, "login", user=user)
    await db.commit()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=int(session_ttl().total_seconds()),
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )
    return user


async def logout_current_session(db: AsyncSession, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = await db.scalar(select(DbSession).where(DbSession.token_hash == hash_token(token)))
        if session and session.revoked_at is None:
            session.revoked_at = now_utc()
            user = await db.get(User, session.user_id)
            await record_event(db, request, "logout", user=user)
            await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


async def send_password_reset(db: AsyncSession, request: Request, email: str) -> None:
    email_norm = normalize_email(email)
    user = await db.scalar(select(User).where(User.email == email_norm))
    if user and user.is_active:
        token = new_token()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=now_utc() + reset_ttl(),
            )
        )
        reset_url = f"{public_base_url()}/reset-password?token={token}"
        await send_auth_email(
            user.email,
            "Reset your FinEdgar password",
            f"Open this link to reset your FinEdgar password:\n\n{reset_url}\n\nThis link expires soon.",
        )
        await record_event(db, request, "forgot_password", user=user)
    else:
        await record_event(db, request, "forgot_password_unknown", email=email_norm)
    await db.commit()


async def reset_password(db: AsyncSession, request: Request, token: str, password: str) -> User:
    token_row = await db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    if not token_row or token_row.used_at is not None or _aware(token_row.expires_at) < now_utc():
        await record_event(db, request, "reset_password_failed")
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired reset token")

    user = await db.get(User, token_row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid reset token")
    user.password_hash = hash_password(password)
    user.updated_at = now_utc()
    user.is_verified = True
    token_row.used_at = now_utc()
    await db.execute(
        update(DbSession)
        .where(DbSession.user_id == user.id, DbSession.revoked_at.is_(None))
        .values(revoked_at=now_utc())
    )
    await record_event(db, request, "reset_password", user=user)
    await db.commit()
    await db.refresh(user)
    return user


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    validate_same_origin(request)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    session = await db.scalar(select(DbSession).where(DbSession.token_hash == hash_token(token)))
    if not session or session.revoked_at is not None or _aware(session.expires_at) < now_utc():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired")
    user = await db.get(User, session.user_id)
    if not user or not user.is_active or not user.is_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


async def optional_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = await db.scalar(select(DbSession).where(DbSession.token_hash == hash_token(token)))
    if not session or session.revoked_at is not None or _aware(session.expires_at) < now_utc():
        return None
    user = await db.get(User, session.user_id)
    if not user or not user.is_active or not user.is_verified:
        return None
    return user
