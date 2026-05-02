"""Database session setup for the FastAPI web application.

The web app stores users, sessions, auth tokens, conversations, messages, and
auth audit events in Postgres. This module owns the async SQLAlchemy engine and
the dependency used by routes that need a database session.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_DATABASE_URL = "postgresql+asyncpg://finedgar:finedgar@postgres:5432/finedgar"


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


engine = create_async_engine(
    database_url(),
    pool_pre_ping=True,
    future=True,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def dispose_db() -> None:
    await engine.dispose()
