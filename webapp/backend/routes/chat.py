"""Authenticated chat route.

This endpoint validates the caller's session, checks conversation ownership,
runs the synchronous answer pipeline in a worker thread, and persists the user
and assistant messages in one request path.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.observability import monotonic_seconds, observe_chat, observe_pipeline_error, traced_span

from ..db import get_db
from ..db_models import User
from ..schemas import ChatRequest, ChatResponse
from ..services.pipeline import run_chat
from ..services.auth import current_user
from ..services.conversations import get_conversation, persist_chat_turn

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    start = monotonic_seconds()
    route = req.route_override or "auto"
    try:
        if req.conversation_id:
            conversation = await get_conversation(db, user, req.conversation_id)
            if not conversation:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
        # answer_question is synchronous and can take seconds; offload so we
        # don't block the event loop.
        with traced_span("chat.pipeline", {"finedgar.ticker": req.ticker or "", "finedgar.route": route}):
            response = await asyncio.to_thread(
                run_chat,
                req.question,
                req.ticker,
                req.years,
                req.route_override,
            )
            route = response.route
        with traced_span("chat.persist", {"finedgar.route": route}):
            await persist_chat_turn(
                db,
                user,
                question=req.question,
                ticker=req.ticker,
                years=req.years,
                response=response,
                conversation_id=req.conversation_id,
            )
        observe_chat(route, "ok", monotonic_seconds() - start)
        return response
    except HTTPException:
        observe_chat(route, "http_error", monotonic_seconds() - start)
        raise
    except Exception as e:
        observe_pipeline_error("chat")
        observe_chat(route, "error", monotonic_seconds() - start)
        raise HTTPException(status_code=500, detail=f"pipeline error: {e}") from e
