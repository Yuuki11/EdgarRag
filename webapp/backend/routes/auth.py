"""Authentication HTTP routes.

Routes here are thin wrappers over `services.auth`: they validate request
payloads, enforce same-origin checks for cookie-backed requests, and return the
current public auth state to the React app.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..schemas import (
    AuthStatus,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
    UserPublic,
)
from ..security import validate_same_origin
from ..services.auth import (
    create_user,
    current_user,
    login_user,
    logout_current_session,
    optional_current_user,
    reset_password,
    send_password_reset,
    user_public,
    verify_email_token,
)
from ..db_models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthStatus)
async def register(req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)) -> AuthStatus:
    validate_same_origin(request)
    user = await create_user(db, request, req.email, req.password)
    return AuthStatus(user=user_public(user))


@router.post("/verify-email", response_model=AuthStatus)
async def verify_email(req: TokenRequest, request: Request, db: AsyncSession = Depends(get_db)) -> AuthStatus:
    validate_same_origin(request)
    user = await verify_email_token(db, request, req.token)
    return AuthStatus(user=user_public(user))


@router.post("/login", response_model=AuthStatus)
async def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthStatus:
    validate_same_origin(request)
    user = await login_user(db, request, response, req.email, req.password)
    return AuthStatus(user=user_public(user))


@router.post("/logout", response_model=AuthStatus)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthStatus:
    validate_same_origin(request)
    await logout_current_session(db, request, response)
    return AuthStatus(user=None)


@router.get("/me", response_model=AuthStatus)
async def me(user: User | None = Depends(optional_current_user)) -> AuthStatus:
    return AuthStatus(user=user_public(user) if user else None)


@router.post("/forgot-password", response_model=AuthStatus)
async def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthStatus:
    validate_same_origin(request)
    await send_password_reset(db, request, req.email)
    return AuthStatus(user=None)


@router.post("/reset-password", response_model=AuthStatus)
async def reset_password_route(
    req: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthStatus:
    validate_same_origin(request)
    user = await reset_password(db, request, req.token, req.password)
    return AuthStatus(user=user_public(user))
