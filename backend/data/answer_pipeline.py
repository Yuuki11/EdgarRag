"""Answer pipeline: orchestrates routing, retrieval, XBRL, and LLM generation.

Flow: question → route classification → (XBRL or RAG retrieval + generation) → answer
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.observability import monotonic_seconds, observe_ollama, observe_pipeline_error, traced_span

from .benchmarking import (
    classify_operation,
    classify_route,
    extract_as_of_date,
    extract_metrics,
    extract_quarters,
    extract_years,
    infer_answer_mode,
    infer_answer_shape,
    infer_source_bias,
    infer_time_scope,
)
from .retrieval import (
    curate_evidence,
    retrieve_documents,
    retrieve_passages,
)
from .xbrl_fetcher import METRIC_ALIASES
from .xbrl_reasoning import ComputedAnswer, compute_xbrl_answer

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "finedgar")


def _ollama_generate_url() -> str:
    """Resolve the Ollama generate endpoint at call time for container overrides."""
    return f"{os.getenv('OLLAMA_HOST', OLLAMA_HOST).rstrip('/')}/api/generate"


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    """Full result of answering one question, including debug info."""

    question: str
    ticker: str
    years: list[int]
    route: str  # "xbrl", "rag", "hybrid"
    operation: str
    metrics: list[str]
    answer: str
    # Debug / diagnostics
    xbrl_result: dict | None = None
    retrieved_passages: list[dict] = field(default_factory=list)
    raw_llm_output: str = ""
    latency_ms: float = 0.0
    fallback_used: bool = False
    error: str = ""
    question_plan: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# LLM interaction
# ──────────────────────────────────────────────────────────────────────────────


def _call_ollama(prompt: str, system: str = "", model: str | None = None, timeout: float = 120.0) -> str:
    """Call Ollama generate API and return the response text."""
    options: dict[str, Any] = {
        "temperature": 0.1,
        "top_p": 0.9,
        "num_predict": 1024,
    }
    # When FINEDGAR_FORCE_CPU=1, tell Ollama to load the model into RAM only
    # (no GPU offload). Matches the local/mobile deployment story.
    if os.getenv("FINEDGAR_FORCE_CPU", "0").lower() in {"1", "true", "yes"}:
        options["num_gpu"] = 0
    payload: dict[str, Any] = {
        "model": model or os.getenv("OLLAMA_MODEL", OLLAMA_MODEL),
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if system:
        payload["system"] = system

    start = monotonic_seconds()
    try:
        with httpx.Client(timeout=timeout) as client:
            with traced_span("ollama.generate", {"ollama.model": payload["model"]}):
                resp = client.post(_ollama_generate_url(), json=payload)
            resp.raise_for_status()
            observe_ollama("ok", monotonic_seconds() - start)
            return resp.json().get("response", "").strip()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        observe_ollama("error", monotonic_seconds() - start)
        observe_pipeline_error("ollama")
        logger.error("Ollama call failed: %s", e)
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# RAG answer generation
# ──────────────────────────────────────────────────────────────────────────────

_RAG_SYSTEM = (
    "You are FinEdgar, a financial analysis assistant specializing in SEC filings. "
    "You provide accurate, well-sourced answers about company financials, risk factors, "
    "and filing changes. Always cite your sources (filing name, section, page when available). "
    "Prefer direct extraction over paraphrase. When calculation is required, "
    "show the formula briefly and compute only from provided evidence. "
    "Do not abstain if the answer is explicitly present in the provided evidence."
)


def _render_context(passages: list[dict]) -> str:
    context_parts = []
    for i, passage in enumerate(passages, 1):
        header = (
            f"[Source {i}: {passage.get('ticker', '?')} FY{passage.get('year', '?')} "
            f"{passage.get('doc_type', '')} {passage.get('fiscal_period', '')} "
            f"— {passage.get('section_name', 'Unknown Section')}]"
        )
        context_parts.append(f"{header}\n{passage['text']}")
    return "\n\n---\n\n".join(context_parts)


def _build_extraction_prompt(question: str, passages: list[dict], question_plan: dict[str, Any]) -> str:
    context = _render_context(passages)
    answer_mode = question_plan.get("answer_mode", "narrative")
    answer_shape = question_plan.get("answer_shape", "explanation")
    return (
        "Extract candidate answers from the SEC filing context.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer mode: {answer_mode}\n"
        f"Expected answer shape: {answer_shape}\n\n"
        "Return valid JSON with keys:\n"
        "- answerable: true/false\n"
        "- candidates: array of short candidate answers from the evidence\n"
        "- evidence: array of short supporting snippets or formulas\n"
        "- numeric_value: number or null\n"
        "- entity: string or null\n"
        "- rationale: one short sentence\n"
        "Use only the provided context."
    )


def _build_synthesis_prompt(question: str, passages: list[dict], extracted: dict[str, Any], question_plan: dict[str, Any]) -> str:
    context = _render_context(passages[:4])
    return (
        "Answer the question using only the extracted candidates and evidence.\n\n"
        f"Question: {question}\n"
        f"Question plan: {json.dumps(question_plan, sort_keys=True)}\n"
        f"Extracted candidates JSON:\n{json.dumps(extracted, ensure_ascii=False, indent=2)}\n\n"
        f"Context excerpt:\n{context}\n\n"
        "Answer format:\n"
        "1. Final answer on the first line.\n"
        "2. One short support line with direct evidence or formula.\n"
        "Do not say information is missing if the extracted candidates already contain an answer."
    )


def _parse_extraction_output(raw_output: str) -> dict[str, Any]:
    if not raw_output:
        return {}
    text = raw_output.strip()
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        candidates = [line.strip("-* 0123456789. ") for line in text.splitlines() if line.strip()]
        return {
            "answerable": bool(candidates),
            "candidates": candidates[:3],
            "evidence": candidates[1:3],
            "numeric_value": None,
            "entity": None,
            "rationale": candidates[0] if candidates else "",
        }


def _normalize_first_line(answer: str) -> str:
    if not answer:
        return ""
    first = answer.splitlines()[0].strip()
    return re.sub(r"^\s*\d+\.\s*", "", first).strip()


def _looks_like_abstention(text: str) -> bool:
    text = text.lower()
    return any(
        phrase in text
        for phrase in (
            "cannot find",
            "not found in the provided context",
            "provided excerpts do not contain",
            "cannot determine",
            "information not found",
            "source: none",
            "no relevant information was found",
        )
    )


def _verify_rag_answer(answer: str, extracted: dict[str, Any], question_plan: dict[str, Any]) -> str:
    first_line = _normalize_first_line(answer)
    if first_line and not _looks_like_abstention(first_line):
        if question_plan.get("answer_mode") in {"numeric_lookup", "formula"}:
            if any(ch.isdigit() for ch in first_line):
                return answer
        elif question_plan.get("answer_mode") == "entity_selection":
            if extracted.get("entity") or extracted.get("candidates"):
                return answer
        else:
            return answer

    candidates = extracted.get("candidates") or []
    if not extracted.get("answerable"):
        return answer
    if not candidates:
        return answer

    primary = str(candidates[0]).strip()
    evidence = extracted.get("evidence") or []
    support = str(evidence[0]).strip() if evidence else str(extracted.get("rationale", "")).strip()
    if support:
        return f"{primary}\n{support}"
    return primary


def _answer_via_rag(
    question: str,
    ticker: str | None,
    years: list[int] | None,
    question_plan: dict[str, Any],
) -> tuple[str, list[dict], str]:
    """Run RAG retrieval + LLM generation. Returns (answer, passages, raw_output)."""
    documents = retrieve_documents(question, ticker=ticker, years=years, top_k=4, question_plan=question_plan)
    if not documents:
        return "", [], ""

    passages = retrieve_passages(question, documents, top_k=10, question_plan=question_plan)
    if not passages:
        return "", [], ""

    # Curate evidence — check for missing years
    evidence = curate_evidence(passages, ticker=ticker, years=years, question_plan=question_plan)
    final_passages = evidence["passages"] if evidence["passages"] else passages[:6]

    extraction_prompt = _build_extraction_prompt(question, final_passages[:6], question_plan)
    extracted_raw = _call_ollama(extraction_prompt, system=_RAG_SYSTEM)
    extracted = _parse_extraction_output(extracted_raw)
    synthesis_prompt = _build_synthesis_prompt(question, final_passages[:5], extracted, question_plan)
    raw_output = _call_ollama(synthesis_prompt, system=_RAG_SYSTEM)
    final_answer = _verify_rag_answer(raw_output, extracted, question_plan)

    return final_answer, final_passages[:6], json.dumps(
        {"extraction": extracted_raw, "synthesis": raw_output},
        ensure_ascii=False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# XBRL answer generation
# ──────────────────────────────────────────────────────────────────────────────


def _answer_via_xbrl(
    question: str,
    ticker: str,
    years: list[int],
    metrics: list[str],
    operation: str,
    period: str = "FY",
) -> tuple[str, dict | None]:
    """Run XBRL deterministic computation. Returns (formatted_answer, result_dict)."""
    plan = {
        "operation": operation,
        "ticker": ticker,
        "years": years,
        "metrics": metrics,
        "period": period,
    }

    result = compute_xbrl_answer(plan)
    if result is None:
        return "", None

    answer = _format_xbrl_answer_for_question(question, result)
    return answer, asdict(result)


def _build_xbrl_plan(
    question: str,
    ticker: str,
    years: list[int],
    metrics: list[str],
    operation: str,
    question_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a richer deterministic plan from the raw routing signals."""
    q = question.lower()
    years = sorted(set(years))
    plan: dict[str, Any] = {
        "operation": operation,
        "ticker": ticker,
        "years": years,
        "metrics": list(dict.fromkeys(metrics)),
        "period": "FY",
    }

    if question_plan and question_plan.get("quarter"):
        plan["period"] = question_plan["quarter"]
        if years:
            plan["years"] = [years[-1]]

    if "3 year average" in q and len(years) == 2 and years[1] - years[0] == 2:
        plan["years"] = [years[0], years[0] + 1, years[1]]

    if "fixed asset turnover" in q and len(years) >= 2:
        plan["operation"] = "ratio_avg_balance"
        plan["years"] = years[-2:]
        plan["metrics"] = ["revenue", "net ppe"]
    elif ("return on assets" in q or " roa" in f" {q}") and len(years) >= 2:
        plan["operation"] = "ratio_avg_balance"
        plan["years"] = years[-2:]
        plan["metrics"] = ["net income", "total assets"]
    elif ("return on equity" in q or " roe" in f" {q}") and len(years) >= 2:
        plan["operation"] = "ratio_avg_balance"
        plan["years"] = years[-2:]
        plan["metrics"] = ["net income", "stockholders equity"]
    elif "days payable outstanding" in q or " dpo" in f" {q}":
        plan["operation"] = "dpo"
        plan["years"] = years[-2:]
        plan["metrics"] = ["accounts payable", "inventory", "cost of goods sold"]
    elif "days sales outstanding" in q or " dso" in f" {q}":
        plan["operation"] = "dso"
        plan["years"] = years[-2:]
        plan["metrics"] = ["accounts receivable", "revenue"]
    elif "days inventory outstanding" in q or " dio" in f" {q}":
        plan["operation"] = "dio"
        plan["years"] = years[-2:]
        plan["metrics"] = ["inventory", "cost of goods sold"]
    elif "cash conversion cycle" in q or " ccc" in f" {q}":
        plan["operation"] = "ccc"
        plan["years"] = years[-2:]
        plan["metrics"] = ["accounts payable", "accounts receivable", "inventory", "revenue", "cost of goods sold"]
    elif "3 year average" in q and "capex" in q and "revenue" in q and len(plan["years"]) >= 3:
        plan["operation"] = "three_year_avg_ratio"
        plan["metrics"] = ["capex", "revenue"]
    elif "3 year average" in q and "operating income" in q and "margin" in q and len(plan["years"]) >= 3:
        plan["operation"] = "three_year_avg_ratio"
        plan["metrics"] = ["operating income", "revenue"]
    elif "cagr" in q and len(years) == 2 and metrics:
        plan["operation"] = "cagr"
        plan["metrics"] = [metrics[0]]
    elif "retention ratio" in q:
        plan["operation"] = "retention_ratio"
        plan["metrics"] = ["dividends", "net income"]
    elif "dividend payout ratio" in q or ("payout ratio" in q and "dividend" in q):
        plan["operation"] = "payout_ratio"
        plan["metrics"] = ["dividends", "net income"]
    elif "unadjusted ebitda % margin" in q or "ebitda % margin" in q:
        plan["operation"] = "ebitda_margin"
        plan["metrics"] = ["operating income", "depreciation", "revenue"]
    elif (
        ("depreciation and amortization" in q or "d&a" in q)
        and ("margin" in q or "%" in q or "percent" in q)
    ):
        plan["operation"] = "ratio"
        plan["metrics"] = ["depreciation", "revenue"]
    elif "ebitda less capex" in q:
        plan["operation"] = "ebitda_less_capex"
        plan["metrics"] = ["operating income", "depreciation", "capex"]
    elif "unadjusted operating income + depreciation" in q or (
        "unadjusted ebitda" in q and "margin" not in q
    ):
        plan["operation"] = "ebitda"
        plan["metrics"] = ["operating income", "depreciation"]
    elif "quick ratio" in q:
        plan["operation"] = "quick_ratio"
        plan["metrics"] = ["cash", "accounts receivable", "total current liabilities"]
    elif "inventory turnover" in q:
        plan["operation"] = "inventory_turnover"
        plan["years"] = years[-2:]
        plan["metrics"] = ["inventory", "cost of goods sold"]
    elif "free cashflow conversion" in q or "free cash flow conversion" in q:
        plan["operation"] = "free_cash_flow_conversion"
        plan["metrics"] = ["operating cash flow", "capex", "net income"]
    elif "capital-intensive" in q or "capital intensive" in q:
        plan["operation"] = "capital_intensity"
        plan["metrics"] = ["capex", "revenue", "net ppe", "total assets"]
    elif "among operations, investing, and financing activities" in q:
        plan["operation"] = "cashflow_activity_max"
        plan["metrics"] = ["operating cash flow", "investing cash flow", "financing cash flow"]

    return plan


def _is_narrative_finance_question(question: str) -> bool:
    q = question.lower()
    if any(
        phrase in q
        for phrase in (
            "what drove",
            "what are major acquisitions",
            "what acquisitions",
            "which segment",
            "capital-intensive",
            "capital intensive",
            "industry does",
            "primarily operate in",
            "explain why",
            "state that and explain why",
        )
    ):
        return True
    if "stable trend" in q or "maintain a stable trend" in q:
        return True
    return False


def _format_xbrl_answer_for_question(question: str, result: ComputedAnswer) -> str:
    """Format deterministic answers to match common benchmark unit requests."""
    if isinstance(result.value, bool):
        return "yes" if result.value else "no"

    if result.value is None or not isinstance(result.value, (int, float)):
        return result.formatted_value

    q = question.lower()
    value = float(result.value)

    if result.operation == "cashflow_activity_max":
        if "among operations, investing, and financing activities" in q:
            label = result.formatted_value.split(" had the highest", 1)[0]
            return result.formatted_value if "($" in result.formatted_value else f"{label} had the highest cash flow"

    if "usd millions" in q or "usd million" in q or "in millions" in q:
        if result.unit == "USD":
            return f"${value / 1_000_000:,.2f}"
    if "usd billions" in q or "usd billion" in q or "in billions" in q:
        if result.unit == "USD":
            return f"${value / 1_000_000_000:,.2f}"
    if "percent" in q or "percents" in q or "%" in q:
        if result.unit in {"ratio", "pure"} or "margin" in " ".join(result.metrics).lower():
            return f"{value * 100:.2f}%"
        if result.unit == "percent":
            return f"{value:.2f}%"
    if result.unit == "days":
        return f"{value:.2f}"

    return result.formatted_value


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────


def answer_question(
    question: str,
    ticker: str | None = None,
    years: list[int] | None = None,
    route_override: str | None = None,
) -> PipelineResult:
    """Answer a single FinanceBench question using the full pipeline.

    Args:
        question: The question text
        ticker: Company ticker (e.g. "AAPL")
        years: Fiscal years relevant to the question
        route_override: Force a specific route ("xbrl", "rag", "hybrid")

    Returns:
        PipelineResult with answer and diagnostic information
    """
    start = time.perf_counter()

    # Extract routing signals
    known_metrics = list(METRIC_ALIASES.keys())
    operation = classify_operation(question)
    metrics = list(dict.fromkeys(extract_metrics(question, known_metrics)))
    detected_years = list(extract_years(question))
    quarter_refs = list(extract_quarters(question))
    as_of_date = extract_as_of_date(question)

    # Keep both explicit benchmark years and years mentioned in the question.
    effective_years = sorted({*(years or []), *detected_years}) if (years or detected_years) else []

    q_lower = question.lower()
    answer_mode = infer_answer_mode(question, operation)
    time_scope = infer_time_scope(tuple(effective_years), tuple(quarter_refs), as_of_date)
    source_bias = infer_source_bias(question, answer_mode)
    answer_shape = infer_answer_shape(question, answer_mode)
    question_plan = {
        "operation": operation,
        "metrics": metrics,
        "answer_mode": answer_mode,
        "time_scope": time_scope,
        "source_bias": source_bias,
        "answer_shape": answer_shape,
        "quarter": quarter_refs[0].period if quarter_refs else None,
        "as_of_date": as_of_date,
    }

    # Determine route
    if route_override:
        route = route_override
    else:
        route = classify_route(operation, tuple(metrics))

    if _is_narrative_finance_question(question) or answer_mode in {"entity_selection", "narrative"}:
        route = "rag"

    xbrl_plan = _build_xbrl_plan(question, ticker or "", effective_years, metrics, operation, question_plan=question_plan)
    if xbrl_plan.get("operation") == "cashflow_activity_max" and ticker and effective_years:
        route = "xbrl"
    deterministic_ops = {
        "lookup",
        "absolute_change",
        "percentage_change",
        "ratio",
        "ratio_avg_balance",
        "three_year_avg_ratio",
        "cagr",
        "ebitda",
        "ebitda_margin",
        "ebitda_less_capex",
        "payout_ratio",
        "retention_ratio",
        "quick_ratio",
        "inventory_turnover",
        "free_cash_flow_conversion",
        "capital_intensity",
        "dso",
        "dio",
        "dpo",
        "ccc",
        "cashflow_activity_max",
        "existence",
    }
    if (
        route == "rag"
        and ticker
        and effective_years
        and xbrl_plan.get("metrics")
        and xbrl_plan.get("operation") in deterministic_ops
        and (answer_mode not in {"entity_selection", "narrative"} or xbrl_plan.get("operation") == "cashflow_activity_max")
        and any(
            token in q_lower
            for token in (
                "balance sheet",
                "statement of financial position",
                "cash flow",
                "income statement",
                "statement of operations",
                "ratio",
                "margin",
                "days ",
                "working capital",
                "year-over-year change",
                "growth rate",
                "cagr",
                "how much",
                "year end",
            )
        )
    ):
        route = "xbrl"

    result = PipelineResult(
        question=question,
        ticker=ticker or "",
        years=effective_years,
        route=route,
        operation=operation,
        metrics=metrics,
        answer="",
        question_plan=question_plan,
    )

    try:
        if route == "xbrl" and ticker and xbrl_plan.get("metrics"):
            answer, xbrl_result = _answer_via_xbrl(
                question,
                ticker,
                xbrl_plan.get("years", effective_years),
                xbrl_plan.get("metrics", metrics),
                xbrl_plan.get("operation", operation),
                xbrl_plan.get("period", "FY"),
            )
            result.xbrl_result = xbrl_result
            result.operation = xbrl_plan.get("operation", operation)
            result.metrics = list(xbrl_plan.get("metrics", metrics))

            if answer:
                result.answer = answer
            else:
                # XBRL failed — fall back to RAG
                logger.info("XBRL returned None for %s, falling back to RAG", question[:50])
                result.fallback_used = True
                result.route = "rag"
                answer, passages, raw = _answer_via_rag(question, ticker, effective_years, question_plan)
                result.answer = answer
                result.retrieved_passages = passages
                result.raw_llm_output = raw

        elif route in ("rag", "hybrid"):
            answer, passages, raw = _answer_via_rag(question, ticker, effective_years, question_plan)
            result.answer = answer
            result.retrieved_passages = passages
            result.raw_llm_output = raw

        else:
            # No ticker or no metrics for XBRL — use RAG
            answer, passages, raw = _answer_via_rag(question, ticker, effective_years, question_plan)
            result.answer = answer
            result.retrieved_passages = passages
            result.raw_llm_output = raw

    except Exception as e:
        logger.exception("Pipeline error for question: %s", question[:80])
        result.error = str(e)

    result.latency_ms = (time.perf_counter() - start) * 1000
    return result
