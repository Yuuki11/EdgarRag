"""Conversation management routes for chat history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..db_models import User
from ..schemas import (
    ConversationCreateRequest,
    ConversationMessagesResponse,
    ConversationsResponse,
    ConversationSummary,
    ConversationUpdateRequest,
)
from ..services.auth import current_user
from ..services.conversations import (
    conversation_summary,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    messages_for_conversation,
    rename_conversation,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=ConversationsResponse)
async def conversations(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationsResponse:
    return ConversationsResponse(conversations=await list_conversations(db, user))


@router.post("", response_model=ConversationSummary)
async def create(
    req: ConversationCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationSummary:
    conversation = await create_conversation(db, user, req.title)
    return conversation_summary(conversation)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def update(
    conversation_id: str,
    req: ConversationUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationSummary:
    conversation = await get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    conversation = await rename_conversation(db, conversation, req.title)
    return conversation_summary(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    conversation_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    conversation = await get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    await delete_conversation(db, conversation)


@router.get("/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def messages(
    conversation_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationMessagesResponse:
    conversation = await get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return ConversationMessagesResponse(
        conversation=conversation_summary(conversation),
        messages=await messages_for_conversation(db, conversation),
    )
