from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from webapp.backend.db_models import Base, User
from webapp.backend.schemas import ChatResponse
from webapp.backend.security import SESSION_COOKIE, hash_token, verify_password
from webapp.backend.services import auth as auth_service
from webapp.backend.services.conversations import (
    get_conversation,
    list_conversations,
    messages_for_conversation,
    persist_chat_turn,
)


class DummyRequest:
    headers = {"user-agent": "pytest"}
    client = SimpleNamespace(host="127.0.0.1")
    method = "POST"

    @property
    def cookies(self):
        return {}


@pytest_asyncio.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("FINEDGAR_AUTH_SECRET", "pytest-secret")
    monkeypatch.setenv("FINEDGAR_AUTH_COOKIE_SECURE", "0")
    monkeypatch.setenv("FINEDGAR_PUBLIC_BASE_URL", "http://localhost:5173")


@pytest.fixture()
def sent_tokens(monkeypatch):
    tokens: list[str] = []

    async def fake_send(to_email: str, subject: str, body: str) -> None:
        match = re.search(r"token=([A-Za-z0-9_\-]+)", body)
        if match:
            tokens.append(match.group(1))

    monkeypatch.setattr(auth_service, "send_auth_email", fake_send)
    return tokens


@pytest.mark.asyncio
async def test_register_verify_login_logout_and_reset(db_session, sent_tokens):
    request = DummyRequest()
    user = await auth_service.create_user(db_session, request, "USER@example.com", "correct horse battery")

    assert user.email == "user@example.com"
    assert not user.is_verified
    assert user.password_hash != "correct horse battery"
    assert verify_password("correct horse battery", user.password_hash)
    assert sent_tokens

    await auth_service.verify_email_token(db_session, request, sent_tokens[-1])

    response = Response()
    user = await auth_service.login_user(
        db_session,
        request,
        response,
        "user@example.com",
        "correct horse battery",
    )
    assert user.is_verified
    assert SESSION_COOKIE in response.headers["set-cookie"]

    await auth_service.send_password_reset(db_session, request, "user@example.com")
    reset_token = sent_tokens[-1]
    await auth_service.reset_password(db_session, request, reset_token, "new correct horse")

    refreshed = await db_session.get(User, user.id)
    assert refreshed is not None
    assert verify_password("new correct horse", refreshed.password_hash)


@pytest.mark.asyncio
async def test_used_verification_token_is_rejected(db_session, sent_tokens):
    request = DummyRequest()
    await auth_service.create_user(db_session, request, "a@example.com", "correct horse battery")
    token = sent_tokens[-1]
    await auth_service.verify_email_token(db_session, request, token)

    with pytest.raises(Exception):
        await auth_service.verify_email_token(db_session, request, token)


@pytest.mark.asyncio
async def test_chat_history_is_owned_by_user(db_session):
    user_a = User(email="a@example.com", password_hash="hash", is_verified=True)
    user_b = User(email="b@example.com", password_hash="hash", is_verified=True)
    db_session.add_all([user_a, user_b])
    await db_session.commit()
    await db_session.refresh(user_a)
    await db_session.refresh(user_b)

    response = ChatResponse(
        answer="$383.29 billion",
        route="xbrl",
        operation="lookup",
        ticker="AAPL",
        years=[2023],
        metrics=["revenue"],
        citations=[],
        xbrl_evidence=[],
        latency_ms=10.0,
        fallback_used=False,
        error="",
    )
    conversation, assistant = await persist_chat_turn(
        db_session,
        user_a,
        question="What was Apple revenue in FY2023?",
        ticker="AAPL",
        years=[2023],
        response=response,
        conversation_id=None,
    )

    assert response.conversation_id == conversation.id
    assert response.message_id == assistant.id
    assert len(await list_conversations(db_session, user_a)) == 1
    assert len(await list_conversations(db_session, user_b)) == 0
    assert await get_conversation(db_session, user_b, conversation.id) is None

    messages = await messages_for_conversation(db_session, conversation)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].response is not None
    assert messages[1].response.answer == "$383.29 billion"
