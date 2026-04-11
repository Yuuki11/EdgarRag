"""Hierarchical retrieval over parsed filing chunks.

Three-stage retrieval pipeline:
1. Filing/Year Filter — hard metadata filter by ticker + year
2. Section Selection — score sections by relevance, select top sections
3. Chunk Retrieval — lexical scoring within selected sections
"""

from __future__ import annotations

from collections import Counter
import json
import math
import re
from pathlib import Path
from typing import Any


CHUNKS_DIR = Path("data/chunks")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")

# Expanded section hints mapping keywords to likely sections
_SECTION_HINTS: dict[str, list[str]] = {
    # Risk factors
    "risk": ["item_1a"],
    "risk factor": ["item_1a"],
    # MD&A
    "md&a": ["item_7"],
    "management discussion": ["item_7"],
    "management's discussion": ["item_7"],
    # Market risk
    "market risk": ["item_7a"],
    "interest rate risk": ["item_7a"],
    "foreign currency risk": ["item_7a"],
    # Financial statements (broad)
    "financial statement": ["item_8"],
    "cash flow": ["item_8"],
    "balance sheet": ["item_8"],
    "income statement": ["item_8"],
    "statement of operations": ["item_8"],
    "consolidated statements": ["item_8"],
    # Revenue / income — both MD&A and financial statements
    "revenue": ["item_7", "item_8"],
    "net sales": ["item_7", "item_8"],
    "total revenue": ["item_7", "item_8"],
    "net income": ["item_7", "item_8"],
    "operating income": ["item_7", "item_8"],
    "gross profit": ["item_7", "item_8"],
    "gross margin": ["item_7", "item_8"],
    # Expense / cost
    "expense": ["item_7", "item_8"],
    "cost": ["item_7", "item_8"],
    "cost of revenue": ["item_7", "item_8"],
    "cost of sales": ["item_7", "item_8"],
    "operating expense": ["item_7", "item_8"],
    "research and development": ["item_7", "item_8"],
    "selling general": ["item_7", "item_8"],
    "sga": ["item_7", "item_8"],
    # Balance sheet items
    "total assets": ["item_8"],
    "total liabilities": ["item_8"],
    "stockholders equity": ["item_8"],
    "shareholders equity": ["item_8"],
    "current assets": ["item_8"],
    "current liabilities": ["item_8"],
    "inventory": ["item_8"],
    "inventories": ["item_8"],
    "accounts receivable": ["item_8"],
    "accounts payable": ["item_8"],
    "goodwill": ["item_8"],
    "long term debt": ["item_7", "item_8"],
    "debt": ["item_7", "item_8"],
    # Cash flow items
    "capital expenditure": ["item_8"],
    "capex": ["item_8"],
    "depreciation": ["item_8"],
    "free cash flow": ["item_7", "item_8"],
    "operating cash flow": ["item_8"],
    "dividends": ["item_8"],
    "share repurchase": ["item_8"],
    # Business
    "strategy": ["item_1"],
    "business": ["item_1"],
    "segment": ["item_1", "item_7"],
    "product": ["item_1"],
    "competition": ["item_1"],
    # Ratios / margins (MD&A context)
    "margin": ["item_7"],
    "ratio": ["item_7", "item_8"],
    "return on": ["item_7"],
    "eps": ["item_7", "item_8"],
    "earnings per share": ["item_7", "item_8"],
    "shares outstanding": ["item_8"],
}


def _infer_document_id(chunks_path: Path, year: int) -> str:
    if chunks_path.parent.name == str(year):
        return f"10-K_{year}"
    return chunks_path.parent.name


def _infer_doc_type(chunk: dict, chunks_path: Path) -> str:
    form_type = str(chunk.get("form_type", "")).upper()
    if form_type:
        return form_type
    doc_name = chunks_path.parent.name.upper()
    for token in ("10-K", "10-Q", "8-K", "DEF 14A", "EX-99", "EARNINGS"):
        if token in doc_name:
            return token
    return "UNKNOWN"


def _infer_fiscal_period(chunk: dict, year: int) -> str:
    text = str(chunk.get("text", ""))[:200].lower()
    if "three months ended" in text or "first quarter" in text or "q1" in text:
        return "Q1"
    if "six months ended" in text or "second quarter" in text or "q2" in text:
        return "Q2"
    if "nine months ended" in text or "third quarter" in text or "q3" in text:
        return "Q3"
    if str(chunk.get("form_type", "")).upper() == "10-Q":
        return "Q?"
    return "FY"


def _section_family(section: str, section_name: str) -> str:
    section_name_lower = section_name.lower()
    if section == "item_8" or "financial statement" in section_name_lower:
        return "financials"
    if section == "item_7" or "management" in section_name_lower:
        return "mda"
    if section == "item_1a":
        return "risk"
    if section == "item_1":
        return "business"
    return "other"


def _normalize_chunk_record(chunk: dict, chunks_path: Path, year: int) -> dict:
    document_id = chunk.get("document_id") or _infer_document_id(chunks_path, year)
    doc_type = chunk.get("doc_type") or _infer_doc_type(chunk, chunks_path)
    doc_name = chunk.get("doc_name") or document_id
    fiscal_period = chunk.get("fiscal_period") or _infer_fiscal_period(chunk, year)
    section_name = str(chunk.get("section_name", ""))
    return {
        **chunk,
        "document_id": document_id,
        "doc_type": doc_type,
        "doc_name": doc_name,
        "fiscal_period": fiscal_period,
        "section_family": chunk.get("section_family") or _section_family(str(chunk.get("section", "")), section_name),
    }


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(text)]


def infer_section_hints(question: str, question_plan: dict[str, Any] | None = None) -> list[str]:
    """Infer relevant sections from question text using keyword matching."""
    q = question.lower()
    hints: list[str] = []
    # Try longer phrases first for better specificity
    sorted_phrases = sorted(_SECTION_HINTS.keys(), key=len, reverse=True)
    for phrase in sorted_phrases:
        if phrase in q:
            hints.extend(_SECTION_HINTS[phrase])
    if question_plan:
        if question_plan.get("source_bias") == "mda":
            hints.extend(["item_7", "item_1"])
        elif question_plan.get("source_bias") == "financials":
            hints.extend(["item_8", "item_7"])
        elif question_plan.get("source_bias") in {"8k_event", "earnings", "proxy"}:
            hints.extend(["item_1", "item_7"])
    return sorted(set(hints)) if hints else list(_SECTION_HINTS.get("financial statement", []))


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: Filing/Year Filter (hard metadata filter)
# ──────────────────────────────────────────────────────────────────────────────


def _load_chunks(ticker: str, year: int) -> list[dict]:
    """Load all chunks for a specific ticker/year."""
    year_dir = CHUNKS_DIR / ticker.upper() / str(year)
    if not year_dir.exists():
        return []
    all_chunks: list[dict] = []
    chunk_files = []
    direct = year_dir / "chunks.json"
    if direct.exists():
        chunk_files.append(direct)
    chunk_files.extend(sorted(year_dir.rglob("chunks.json")))
    seen: set[Path] = set()
    for chunks_path in chunk_files:
        if chunks_path in seen:
            continue
        seen.add(chunks_path)
        with open(chunks_path, "r", encoding="utf-8") as fh:
            raw_chunks = json.load(fh)
        all_chunks.extend(_normalize_chunk_record(chunk, chunks_path, year) for chunk in raw_chunks)
    return all_chunks


def _doc_candidates(
    ticker: str | None = None,
    years: list[int] | None = None,
) -> list[tuple[str, int, Path]]:
    """List available (ticker, year, path) combinations."""
    candidates: list[tuple[str, int, Path]] = []
    if not CHUNKS_DIR.exists():
        return candidates

    for ticker_dir in CHUNKS_DIR.iterdir():
        if not ticker_dir.is_dir():
            continue
        current_ticker = ticker_dir.name.upper()
        if ticker and current_ticker != ticker.upper():
            continue
        for year_dir in ticker_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            year = int(year_dir.name)
            if years and year not in years:
                continue
            direct = year_dir / "chunks.json"
            nested = sorted(year_dir.rglob("chunks.json"))
            chunk_paths = []
            if direct.exists():
                chunk_paths.append(direct)
            chunk_paths.extend(nested)
            seen_paths: set[Path] = set()
            for chunks_path in chunk_paths:
                if chunks_path in seen_paths:
                    continue
                seen_paths.add(chunks_path)
                candidates.append((current_ticker, year, chunks_path))
    return sorted(candidates)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: Section Selection (soft scoring)
# ──────────────────────────────────────────────────────────────────────────────


def _score_sections(
    chunks: list[dict], question: str, section_hints: list[str], question_plan: dict[str, Any] | None = None
) -> dict[str, float]:
    """Score each section by relevance to the question."""
    question_tokens = Counter(_tokenize(question))
    section_scores: dict[str, float] = {}
    section_chunk_counts: dict[str, int] = {}

    for chunk in chunks:
        section = chunk["section"]
        section_chunk_counts[section] = section_chunk_counts.get(section, 0) + 1

        # Aggregate token overlap at section level (sample from first 3 chunks per section)
        if section_chunk_counts[section] <= 3:
            chunk_tokens = Counter(_tokenize(chunk["text"][:500]))
            overlap = sum(
                min(question_tokens[t], chunk_tokens[t]) for t in question_tokens
            )
            section_scores[section] = section_scores.get(section, 0.0) + overlap * 0.3

    # Apply section hint bonuses
    for section in section_scores:
        if section in section_hints:
            section_scores[section] += 5.0

    # Fallback: if no section hints matched, boost item_8 (financial statements)
    # and item_7 (MD&A) as the most common answer locations
    if not section_hints:
        for section in section_scores:
            if section == "item_8":
                section_scores[section] += 3.0
            elif section == "item_7":
                section_scores[section] += 2.0

    if question_plan:
        for chunk in chunks[:20]:
            section = chunk["section"]
            family = chunk.get("section_family")
            if question_plan.get("source_bias") == "mda" and family == "mda":
                section_scores[section] = section_scores.get(section, 0.0) + 2.0
            if question_plan.get("source_bias") == "financials" and family == "financials":
                section_scores[section] = section_scores.get(section, 0.0) + 2.0

    return section_scores


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3: Chunk Retrieval within Selected Sections
# ──────────────────────────────────────────────────────────────────────────────


def _score_chunks(
    chunks: list[dict],
    question: str,
    section_hints: list[str],
    selected_sections: set[str],
    question_plan: dict[str, Any] | None = None,
) -> list[dict]:
    """Score individual chunks within selected sections."""
    question_tokens = Counter(_tokenize(question))
    q_lower = question.lower()
    scored: list[dict] = []

    for chunk in chunks:
        if chunk["section"] not in selected_sections:
            continue

        chunk_tokens = Counter(_tokenize(chunk["text"]))
        overlap = sum(
            min(question_tokens[t], chunk_tokens[t]) for t in question_tokens
        )
        score = float(overlap)
        text_lower = chunk["text"].lower()

        # Section hint bonus
        if chunk["section"] in section_hints:
            score += 4.0

        # Recency bonus (earlier chunks in a section tend to have key data)
        score += 0.1 * max(0, 6 - chunk.get("chunk_index", 0))

        # Table bonus: table chunks may be more relevant for numeric questions
        if chunk.get("chunk_type") == "table":
            score += 1.5
            if any(token in q_lower for token in ("how much", "what is", "what was", "ratio", "margin", "days ", "percent")):
                score += 1.0

        # Narrative questions should prefer explanatory prose over tables.
        if any(token in q_lower for token in ("why", "what drove", "explain", "describe", "discuss")):
            if chunk.get("chunk_type") != "table":
                score += 1.5

        # Exact phrase matches for high-signal financial cues.
        for phrase in (
            "balance sheet",
            "cash flow",
            "statement of operations",
            "income statement",
            "accounts payable",
            "accounts receivable",
            "inventory",
            "capital expenditure",
            "operating income",
            "net income",
            "revenue",
            "dividends",
            "market risk",
        ):
            if phrase in q_lower and phrase in text_lower:
                score += 1.25

        # Passage mentions target fiscal year(s).
        for year_token in re.findall(r"\b(20\d{2}|19\d{2})\b", q_lower):
            if year_token in text_lower:
                score += 0.75

        if question_plan:
            if question_plan.get("answer_mode") in {"numeric_lookup", "formula"}:
                if chunk.get("chunk_type") == "table" or chunk.get("section_family") == "financials":
                    score += 1.0
            if question_plan.get("answer_mode") in {"entity_selection", "narrative"}:
                if chunk.get("chunk_type") != "table" or chunk.get("section_family") in {"mda", "business"}:
                    score += 1.0
            if question_plan.get("quarter") and chunk.get("fiscal_period") == question_plan.get("quarter"):
                score += 1.5
            if question_plan.get("source_bias") == "earnings" and chunk.get("doc_type") in {"8-K", "EX-99", "EARNINGS"}:
                score += 2.0
            if question_plan.get("source_bias") == "proxy" and chunk.get("doc_type") == "DEF 14A":
                score += 2.5
            if question_plan.get("source_bias") == "8k_event" and chunk.get("doc_type") == "8-K":
                score += 2.0

        scored.append({**chunk, "score": score})

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def retrieve_documents(
    question: str,
    ticker: str | None = None,
    years: list[int] | None = None,
    top_k: int = 3,
    question_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Stage 1: Retrieve candidate filing documents by metadata."""
    hints = set(infer_section_hints(question, question_plan=question_plan))
    question_tokens = Counter(_tokenize(question))

    scored: list[dict[str, Any]] = []
    for doc_ticker, doc_year, path in _doc_candidates(ticker=ticker, years=years):
        with open(path, "r", encoding="utf-8") as fh:
            chunks = [_normalize_chunk_record(chunk, path, doc_year) for chunk in json.load(fh)]
        section_names = {chunk["section"] for chunk in chunks}
        text_sample = " ".join(chunk["section_name"] for chunk in chunks[:6])
        doc_types = {chunk.get("doc_type", "UNKNOWN") for chunk in chunks[:10]}
        score = 0.0
        if hints:
            score += 2.0 * len(hints.intersection(section_names))
        score += 0.5 * sum(question_tokens[token] for token in _tokenize(text_sample))
        score += math.log(len(chunks) + 1, 10)
        if question_plan:
            source_bias = question_plan.get("source_bias")
            if source_bias == "earnings" and doc_types.intersection({"8-K", "EX-99", "EARNINGS"}):
                score += 3.0
            if source_bias == "proxy" and "DEF 14A" in doc_types:
                score += 3.5
            if source_bias == "8k_event" and "8-K" in doc_types:
                score += 2.5
            if source_bias == "financials" and doc_types.intersection({"10-K", "10-Q"}):
                score += 1.5
        scored.append(
            {
                "ticker": doc_ticker,
                "year": doc_year,
                "chunks_path": str(path),
                "available_sections": sorted(section_names),
                "doc_types": sorted(doc_types),
                "score": score,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def _reciprocal_rank_fusion(
    *result_lists: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Combine multiple ranked lists using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank)) for each list containing the document.
    Documents are identified by (ticker, year, section, chunk_index).
    """
    # Build a unique key for each passage
    def _key(p: dict) -> str:
        return (
            f"{p.get('ticker', '')}|{p.get('year', '')}|{p.get('document_id', '')}|"
            f"{p.get('section', '')}|{p.get('chunk_index', '')}"
        )

    scores: dict[str, float] = {}
    passages: dict[str, dict] = {}

    for result_list in result_lists:
        for rank, passage in enumerate(result_list):
            key = _key(passage)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in passages:
                passages[key] = passage

    # Sort by RRF score
    ranked_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    result = []
    for key in ranked_keys:
        p = passages[key].copy()
        p["rrf_score"] = scores[key]
        p["score"] = scores[key]  # Use RRF as primary score
        result.append(p)

    return result


def _heuristic_rerank(question: str, passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply a cheap domain-aware rerank on already retrieved passages."""
    q_lower = question.lower()
    reranked = []
    for rank, passage in enumerate(passages):
        score = float(passage.get("score", 0.0))
        text_lower = passage.get("text", "").lower()
        section_name = str(passage.get("section_name", "")).lower()

        if "risk" in q_lower and "risk" in section_name:
            score += 2.0
        if any(token in q_lower for token in ("balance sheet", "statement of financial position")) and "financial statements" in section_name:
            score += 2.0
        if any(token in q_lower for token in ("cash flow", "statement of cash flows")) and "financial statements" in section_name:
            score += 1.5
        if any(token in q_lower for token in ("management discussion", "what drove", "why")) and "management" in section_name:
            score += 2.0
        if passage.get("chunk_type") == "table" and any(token in q_lower for token in ("how much", "what is", "what was", "ratio", "margin", "days ", "percent")):
            score += 1.0
        if any(token in q_lower for token in ("guidance", "expects", "outlook")) and passage.get("doc_type") in {"8-K", "EX-99", "EARNINGS"}:
            score += 1.5
        if any(token in q_lower for token in ("agm", "shareholder vote", "nominee", "proposal")) and passage.get("doc_type") == "DEF 14A":
            score += 2.0
        if rank < 3:
            score += 0.25

        reranked.append({**passage, "score": score})

    reranked.sort(key=lambda item: item["score"], reverse=True)
    return reranked


def _expand_with_neighbors(
    passages: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    top_k: int,
    neighbor_window: int = 1,
) -> list[dict[str, Any]]:
    """Expand high-value hits with adjacent chunks from the same section."""
    if not passages:
        return passages

    doc_cache: dict[str, list[dict[str, Any]]] = {}
    expanded: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _key(passage: dict[str, Any]) -> str:
        return (
            f"{passage.get('ticker')}|{passage.get('year')}|{passage.get('document_id', '')}|"
            f"{passage.get('section')}|{passage.get('chunk_index')}"
        )

    doc_paths = {(doc["ticker"], doc["year"]): doc for doc in documents}
    seed_passages = passages[: max(top_k, 5)]

    for passage in seed_passages:
        passage_key = _key(passage)
        if passage_key not in seen:
            expanded.append(passage)
            seen.add(passage_key)

        ticker = passage.get("ticker")
        year = passage.get("year")
        doc = doc_paths.get((ticker, year))
        if not doc:
            continue
        chunks_path = doc["chunks_path"]
        if chunks_path not in doc_cache:
            with open(chunks_path, "r", encoding="utf-8") as fh:
                doc_cache[chunks_path] = json.load(fh)

        current_index = int(passage.get("chunk_index", 0))
        current_section = passage.get("section")
        current_document = passage.get("document_id", "")
        for candidate in doc_cache[chunks_path]:
            if candidate.get("section") != current_section:
                continue
            if candidate.get("document_id", "") != current_document:
                continue
            candidate_index = int(candidate.get("chunk_index", -999))
            if 0 < abs(candidate_index - current_index) <= neighbor_window:
                merged = {**candidate, "score": float(passage.get("score", 0.0)) - 0.35}
                candidate_key = _key(merged)
                if candidate_key not in seen:
                    expanded.append(merged)
                    seen.add(candidate_key)

    expanded.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return expanded[: max(top_k, 8)]


def retrieve_passages(
    question: str,
    documents: list[dict[str, Any]],
    top_k: int = 8,
    question_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Stage 2+3+4: Select sections, score chunks, optionally use dense retrieval + reranking."""
    section_hints = infer_section_hints(question, question_plan=question_plan)

    # ── Lexical retrieval (always available) ──
    lexical_passages: list[dict[str, Any]] = []

    for doc in documents:
        with open(doc["chunks_path"], "r", encoding="utf-8") as fh:
            chunks = [_normalize_chunk_record(chunk, Path(doc["chunks_path"]), doc["year"]) for chunk in json.load(fh)]

        # Stage 2: Score and select top sections
        section_scores = _score_sections(chunks, question, section_hints, question_plan=question_plan)
        if section_scores:
            sorted_sections = sorted(
                section_scores.items(), key=lambda x: x[1], reverse=True
            )
            selected = {s for s, _ in sorted_sections[:3]}
        else:
            selected = {chunk["section"] for chunk in chunks}

        # Stage 3: Score chunks within selected sections
        scored_chunks = _score_chunks(chunks, question, section_hints, selected, question_plan=question_plan)

        for chunk in scored_chunks:
            chunk["score"] += doc["score"]
            lexical_passages.append(chunk)

    lexical_passages.sort(key=lambda item: item["score"], reverse=True)
    lexical_top = lexical_passages[:20]

    # ── Dense retrieval (if vector index available) ──
    dense_top: list[dict[str, Any]] = []
    try:
        from .embeddings import get_index

        index = get_index()
        if index is not None:
            # Use the same ticker/year constraints from documents
            for doc in documents:
                results = index.search(
                    query=question,
                    ticker=doc["ticker"],
                    year=doc["year"],
                    sections=list({s for s, _ in sorted(
                        _score_sections(
                            [_normalize_chunk_record(chunk, Path(doc["chunks_path"]), doc["year"]) for chunk in json.load(open(doc["chunks_path"]))],
                            question,
                            section_hints,
                            question_plan=question_plan,
                        ).items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:3]}) if section_hints else None,
                    top_k=20,
                )
                dense_top.extend(results)
            dense_top.sort(key=lambda x: x.get("dense_score", 0), reverse=True)
            dense_top = dense_top[:20]
    except ImportError:
        pass

    # ── Fusion ──
    if dense_top:
        fused = _reciprocal_rank_fusion(lexical_top, dense_top)
    else:
        fused = lexical_top

    fused = _heuristic_rerank(question, fused)
    fused = _expand_with_neighbors(fused, documents, top_k=top_k)
    return fused[:top_k]


def curate_evidence(
    passages: list[dict[str, Any]],
    ticker: str | None = None,
    years: list[int] | None = None,
    question_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Filter passages and flag missing comparison evidence."""
    filtered = []
    seen_years: set[int] = set()
    seen_table = False
    seen_prose = False
    for passage in passages:
        if ticker and passage["ticker"].upper() != ticker.upper():
            continue
        if years and int(passage["year"]) not in years:
            continue
        if question_plan and question_plan.get("quarter"):
            if passage.get("fiscal_period") not in {question_plan.get("quarter"), "Q?", "FY"}:
                continue
        filtered.append(passage)
        seen_years.add(int(passage["year"]))
        seen_table = seen_table or passage.get("chunk_type") == "table" or passage.get("section_family") == "financials"
        seen_prose = seen_prose or passage.get("chunk_type") != "table"

    if question_plan and question_plan.get("answer_mode") in {"numeric_lookup", "formula"} and not seen_table:
        for passage in passages:
            if passage not in filtered and (passage.get("chunk_type") == "table" or passage.get("section_family") == "financials"):
                filtered.append(passage)
                break
    if question_plan and question_plan.get("answer_mode") in {"entity_selection", "narrative"} and not seen_prose:
        for passage in passages:
            if passage not in filtered and passage.get("chunk_type") != "table":
                filtered.append(passage)
                break

    missing_years = sorted(set(years or []) - seen_years)
    return {
        "passages": filtered,
        "missing_years": missing_years,
        "needs_complementary_retrieval": bool(missing_years),
    }
