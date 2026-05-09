"""Authenticated operator overview API.

The admin endpoint is read-only. It gathers runtime, data artifact, database,
auth, and Kubernetes metadata for the in-app dashboard.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..db_models import AuthEvent, Conversation, Message, Session as DbSession, User
from ..schemas import (
    AdminAuthEvent,
    AdminDataArtifact,
    AdminMetric,
    AdminOverview,
    AdminRuntime,
)
from ..security import now_utc
from ..services.auth import current_user
from ..services.companies import CHUNKS_DIR, load_companies
from .health import REPO_ROOT, XBRL_CACHE, healthz

router = APIRouter(prefix="/api/admin", tags=["admin"])

VECTOR_INDEX = REPO_ROOT / "data" / "vector_index"


def _count_files(path: Path, pattern: str = "*") -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.rglob(pattern) if child.is_file())


def _runtime() -> AdminRuntime:
    return AdminRuntime(
        environment=os.getenv("FINEDGAR_ENV", os.getenv("ENVIRONMENT", "local")),
        release=os.getenv("FINEDGAR_RELEASE", "local-dev"),
        pod_name=os.getenv("POD_NAME") or os.getenv("HOSTNAME"),
        namespace=os.getenv("POD_NAMESPACE"),
        node_name=os.getenv("NODE_NAME"),
        running_in_kubernetes=bool(os.getenv("KUBERNETES_SERVICE_HOST")),
    )


@router.get("/overview", response_model=AdminOverview)
async def overview(
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminOverview:
    companies = load_companies()
    total_years = sum(len(company.years) for company in companies)
    sectors = {company.sector for company in companies if company.sector}

    user_count = await db.scalar(select(func.count()).select_from(User))
    conversation_count = await db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.deleted_at.is_(None))
    )
    message_count = await db.scalar(select(func.count()).select_from(Message))
    active_session_count = await db.scalar(
        select(func.count())
        .select_from(DbSession)
        .where(DbSession.revoked_at.is_(None), DbSession.expires_at > now_utc())
    )

    recent_rows = (
        await db.execute(select(AuthEvent).order_by(AuthEvent.created_at.desc()).limit(8))
    ).scalars()

    health = healthz()
    return AdminOverview(
        generated_at=now_utc().isoformat(),
        runtime=_runtime(),
        health=health,
        metrics=[
            AdminMetric(
                label="Ollama",
                value="reachable" if health.ollama_reachable else "unreachable",
                status="ok" if health.ollama_reachable else "warn",
                detail=f"{health.ollama_model} at {health.ollama_host}",
            ),
            AdminMetric(
                label="Indexed companies",
                value=len(companies),
                status="ok" if companies else "warn",
                detail=f"{len(sectors)} sectors, {total_years} company-year scopes",
            ),
            AdminMetric(
                label="XBRL cache",
                value="warm" if health.xbrl_cache_warm else "cold",
                status="ok" if health.xbrl_cache_warm else "warn",
                detail=str(XBRL_CACHE.relative_to(REPO_ROOT)),
            ),
            AdminMetric(
                label="Compute mode",
                value=health.compute_mode,
                status="neutral",
                detail="CPU-forced runtime" if health.compute_mode == "cpu" else "GPU/accelerator auto-detect allowed",
            ),
            AdminMetric(label="Users", value=user_count or 0, status="neutral"),
            AdminMetric(label="Active sessions", value=active_session_count or 0, status="neutral"),
            AdminMetric(label="Conversations", value=conversation_count or 0, status="neutral"),
            AdminMetric(label="Messages", value=message_count or 0, status="neutral"),
        ],
        data_artifacts=[
            AdminDataArtifact(
                name="Companies catalog",
                path="data/companies.json",
                present=(REPO_ROOT / "data" / "companies.json").is_file(),
                files=1 if (REPO_ROOT / "data" / "companies.json").is_file() else 0,
                detail=f"{len(companies)} tickers loaded",
            ),
            AdminDataArtifact(
                name="Filing chunks",
                path=str(CHUNKS_DIR.relative_to(REPO_ROOT)),
                present=CHUNKS_DIR.is_dir(),
                files=_count_files(CHUNKS_DIR, "*.json"),
                detail="retrieval evidence",
            ),
            AdminDataArtifact(
                name="XBRL cache",
                path=str(XBRL_CACHE.relative_to(REPO_ROOT)),
                present=XBRL_CACHE.is_dir(),
                files=_count_files(XBRL_CACHE, "*.json"),
                detail="structured SEC facts",
            ),
            AdminDataArtifact(
                name="Vector indexes",
                path=str(VECTOR_INDEX.relative_to(REPO_ROOT)),
                present=VECTOR_INDEX.is_dir(),
                files=_count_files(VECTOR_INDEX),
                detail="FAISS retrieval indexes",
            ),
        ],
        recent_auth_events=[
            AdminAuthEvent(
                event_type=row.event_type,
                email=row.email,
                created_at=row.created_at.isoformat(),
            )
            for row in recent_rows
        ],
    )
