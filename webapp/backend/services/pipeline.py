"""Thin adapter around backend.data.answer_pipeline for the web app."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.data.answer_pipeline import PipelineResult, answer_question  # noqa: E402

from ..schemas import ChatResponse, Citation, XbrlEvidence


def run_chat(
    question: str,
    ticker: str | None,
    years: list[int] | None,
    route_override: str | None,
) -> ChatResponse:
    result: PipelineResult = answer_question(
        question=question,
        ticker=ticker,
        years=years,
        route_override=route_override,
    )
    return _to_response(result)


def _to_response(r: PipelineResult) -> ChatResponse:
    citations: list[Citation] = []
    for i, p in enumerate(r.retrieved_passages, 1):
        text = p.get("text") or ""
        citations.append(
            Citation(
                index=i,
                ticker=p.get("ticker"),
                year=p.get("year"),
                section=p.get("section_name"),
                doc_type=p.get("doc_type"),
                fiscal_period=p.get("fiscal_period"),
                snippet=(text[:280] + "…") if len(text) > 280 else text,
            )
        )

    xbrl_evidence: list[XbrlEvidence] = []
    if isinstance(r.xbrl_result, dict):
        facts = r.xbrl_result.get("facts") or r.xbrl_result.get("evidence") or []
        if isinstance(facts, list):
            for f in facts:
                if not isinstance(f, dict):
                    continue
                xbrl_evidence.append(
                    XbrlEvidence(
                        concept=f.get("concept"),
                        value=f.get("value"),
                        unit=f.get("unit"),
                        period=f.get("period") or f.get("fy"),
                        accession=f.get("accn") or f.get("accession"),
                        form=f.get("form"),
                    )
                )

    return ChatResponse(
        conversation_id=None,
        message_id=None,
        answer=r.answer or "",
        route=r.route,
        operation=r.operation or "",
        ticker=r.ticker or None,
        years=list(r.years or []),
        metrics=list(r.metrics or []),
        citations=citations,
        xbrl_evidence=xbrl_evidence,
        latency_ms=r.latency_ms,
        fallback_used=r.fallback_used,
        error=r.error or "",
    )
