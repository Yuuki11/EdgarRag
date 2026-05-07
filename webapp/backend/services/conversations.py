"""Conversation and message persistence helpers.

All queries are scoped by user before returning or mutating conversation state.
The chat route calls this layer after the answer pipeline returns so the UI can
reload prior conversations from Postgres.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db_models import Conversation, Message, User, utcnow
from ..schemas import ChatResponse, ConversationSummary, MessageHistory


def title_from_question(question: str) -> str:
    title = " ".join(question.strip().split())
    if not title:
        return "New chat"
    return title[:77] + "..." if len(title) > 80 else title


def conversation_summary(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
    )


async def list_conversations(db: AsyncSession, user: User) -> list[ConversationSummary]:
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc())
    )
    return [conversation_summary(c) for c in rows]


async def create_conversation(db: AsyncSession, user: User, title: str) -> Conversation:
    conversation = Conversation(user_id=user.id, title=title.strip() or "New chat")
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_conversation(db: AsyncSession, user: User, conversation_id: str) -> Conversation | None:
    return await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
        )
    )


async def rename_conversation(db: AsyncSession, conversation: Conversation, title: str) -> Conversation:
    conversation.title = title.strip() or "New chat"
    conversation.updated_at = utcnow()
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(db: AsyncSession, conversation: Conversation) -> None:
    conversation.deleted_at = utcnow()
    conversation.updated_at = utcnow()
    await db.commit()


async def messages_for_conversation(db: AsyncSession, conversation: Conversation) -> list[MessageHistory]:
    rows = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    )
    messages: list[MessageHistory] = []
    for row in rows:
        response = None
        if row.response_json:
            response = ChatResponse(**row.response_json)
        messages.append(
            MessageHistory(
                id=row.id,
                role=row.role,
                content=row.content,
                ticker=row.ticker,
                years=row.years,
                response=response,
                created_at=row.created_at.isoformat(),
            )
        )
    return messages


async def persist_chat_turn(
    db: AsyncSession,
    user: User,
    *,
    question: str,
    ticker: str | None,
    years: list[int] | None,
    response: ChatResponse,
    conversation_id: str | None,
) -> tuple[Conversation, Message]:
    conversation = None
    if conversation_id:
        conversation = await get_conversation(db, user, conversation_id)
    if conversation is None:
        conversation = Conversation(user_id=user.id, title=title_from_question(question))
        db.add(conversation)
        await db.flush()

    db.add(
        Message(
            conversation_id=conversation.id,
            user_id=user.id,
            role="user",
            content=question,
            ticker=ticker,
            years=years,
        )
    )
    assistant = Message(
        conversation_id=conversation.id,
        user_id=user.id,
        role="assistant",
        content=response.answer,
        ticker=response.ticker,
        years=response.years,
        route=response.route,
        operation=response.operation,
        metrics=response.metrics,
    )
    db.add(assistant)
    await db.flush()

    response.conversation_id = conversation.id
    response.message_id = assistant.id
    assistant.response_json = response.model_dump(mode="json")
    conversation.updated_at = utcnow()
    await db.commit()
    await db.refresh(conversation)
    await db.refresh(assistant)
    return conversation, assistant
