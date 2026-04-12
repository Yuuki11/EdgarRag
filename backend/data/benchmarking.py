"""Benchmark governance utilities for FinanceBench-safe development.

This module keeps benchmark metadata separate from training generation.
It provides:

- a normalized tuple shape for overlap checks
- FinanceBench manifest generation from the public dataset
- helpers for labeling routes and operations consistently
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_YEAR_RE = re.compile(r"\b(?:FY)?(20\d{2}|19\d{2})\b", re.IGNORECASE)
_QUARTER_RE = re.compile(
    r"\b(?:fy)?\s*(20\d{2}|19\d{2})\s*(?:q([1-4])|h([12]))\b|\bq([1-4])\s*(?:fy)?\s*(20\d{2}|19\d{2})\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?:as of|on)\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(20\d{2}|19\d{2})\b"
)


@dataclass(frozen=True)
class QuarterRef:
    year: int
    period: str


@dataclass(frozen=True)
class QuestionPlan:
    operation: str
    metrics: tuple[str, ...]
    answer_mode: str
    time_scope: str
    answer_shape: str
    source_bias: str
    quarter: str | None = None
    as_of_date: str | None = None


@dataclass(frozen=True)
class NormalizedTuple:
    """Benchmark-safe normalized representation of a QA task."""

    ticker: str
    years: tuple[int, ...]
    metrics: tuple[str, ...]
    operation: str

    def to_key(self) -> str:
        years = ",".join(str(year) for year in self.years)
        metrics = ",".join(self.metrics)
        return f"{self.ticker}|{years}|{metrics}|{self.operation}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "years": list(self.years),
            "metrics": list(self.metrics),
            "operation": self.operation,
        }


def stable_bucket(key: str, buckets: int = 100) -> int:
    """Return a stable integer bucket for a key."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def load_company_lookup(
    companies_json_path: str | Path = "data/companies.json",
) -> tuple[dict[str, str], dict[str, str]]:
    """Load bidirectional company/ticker lookups from companies.json."""
    path = Path(companies_json_path)
    companies = json.loads(path.read_text(encoding="utf-8"))

    company_to_ticker: dict[str, str] = {}
    ticker_to_company: dict[str, str] = {}
    for item in companies:
        ticker = item["ticker"].upper()
        name = item["name"].strip()
        company_to_ticker[_canonical_company_name(name)] = ticker
        ticker_to_company[ticker] = name
        base_name = _base_company_name(name)
        if base_name:
            company_to_ticker.setdefault(base_name, ticker)

    sec_lookup_path = path.parent / "company_tickers.json"
    if sec_lookup_path.exists():
        sec_lookup_raw = json.loads(sec_lookup_path.read_text(encoding="utf-8"))
        for entry in sec_lookup_raw.values():
            ticker = str(entry["ticker"]).upper()
            name = str(entry["title"]).strip()
            company_to_ticker.setdefault(_canonical_company_name(name), ticker)
            base_name = _base_company_name(name)
            if base_name:
                company_to_ticker.setdefault(base_name, ticker)
            ticker_to_company.setdefault(ticker, name)

    overrides_path = path.parent / "company_overrides.json"
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        for entry in overrides:
            ticker = str(entry["ticker"]).upper()
            name = str(entry["name"]).strip()
            company_to_ticker[_canonical_company_name(name)] = ticker
            base_name = _base_company_name(name)
            if base_name:
                company_to_ticker[base_name] = ticker
            ticker_to_company[ticker] = name
    return company_to_ticker, ticker_to_company


def _canonical_company_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", " ", name).strip().lower()
    return re.sub(r"\s+", " ", clean)


def _base_company_name(name: str) -> str:
    canonical = _canonical_company_name(name)
    canonical = re.sub(
        r"\b(inc|incorporated|corporation|corp|co|company|plc|ltd|holdings|holding|group|the)\b",
        " ",
        canonical,
    )
    return re.sub(r"\s+", " ", canonical).strip()


_COMPANY_ALIASES = {
    "activision blizzard": "ATVI",
    "3m": "MMM",
    "3m company": "MMM",
    "advanced micro devices": "AMD",
    "amd": "AMD",
    "american express": "AXP",
    "best buy": "BBY",
    "block": "XYZ",
    "boeing": "BA",
    "coca cola": "KO",
    "coca-cola": "KO",
    "corning": "GLW",
    "costco": "COST",
    "cvs health": "CVS",
    "expedia group": "EXPE",
    "foot locker": "FL",
    "general mills": "GIS",
    "johnson and johnson": "JNJ",
    "jpmorgan": "JPM",
    "jpmorgan chase": "JPM",
    "kraft heinz": "KHC",
    "lockheed martin": "LMT",
    "mcgraw hill": "MH",
    "meta": "META",
    "mgm resorts": "MGM",
    "microsoft": "MSFT",
    "netflix": "NFLX",
    "nike": "NKE",
    "paypal": "PYPL",
    "pepsico": "PEP",
    "pfizer": "PFE",
    "ulta beauty": "ULTA",
    "verizon": "VZ",
    "walmart": "WMT",
}


def resolve_company_ticker(company: str, company_to_ticker: dict[str, str]) -> str | None:
    """Resolve a company name to ticker using exact and normalized matching."""
    canonical = _canonical_company_name(company)
    if canonical in _COMPANY_ALIASES:
        return _COMPANY_ALIASES[canonical]
    if canonical in company_to_ticker:
        return company_to_ticker[canonical]

    base = _base_company_name(company)
    if base in _COMPANY_ALIASES:
        return _COMPANY_ALIASES[base]
    if base in company_to_ticker:
        return company_to_ticker[base]

    candidates = []
    for known_name, ticker in company_to_ticker.items():
        known_base = _base_company_name(known_name)
        if not known_base:
            continue
        base_tokens = set(base.split())
        known_tokens = set(known_base.split())
        if not base_tokens or not known_tokens:
            continue
        if base_tokens.issubset(known_tokens) or known_tokens.issubset(base_tokens):
            overlap = len(base_tokens.intersection(known_tokens))
            candidates.append((overlap, len(known_tokens), ticker))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        return candidates[0][2]
    return None


def extract_years(*texts: object) -> tuple[int, ...]:
    """Extract fiscal/calendar years from one or more text fields."""
    years: set[int] = set()
    for text in texts:
        if text is None:
            continue
        for match in _YEAR_RE.findall(str(text)):
            years.add(int(match))
    return tuple(sorted(years))


def extract_quarters(*texts: object) -> tuple[QuarterRef, ...]:
    quarters: list[QuarterRef] = []
    seen: set[tuple[int, str]] = set()
    for text in texts:
        if text is None:
            continue
        for match in _QUARTER_RE.finditer(str(text)):
            year_a, q_a, h_a, q_b, year_b = match.groups()
            year = int(year_a or year_b)
            if q_a or q_b:
                period = f"Q{q_a or q_b}"
            else:
                period = "Q2" if h_a == "1" else "Q4"
            key = (year, period)
            if key not in seen:
                seen.add(key)
                quarters.append(QuarterRef(year=year, period=period))
    return tuple(quarters)


def extract_as_of_date(*texts: object) -> str | None:
    for text in texts:
        if text is None:
            continue
        match = _DATE_RE.search(str(text))
        if match:
            month, day, year = match.groups()
            return f"{month} {int(day)}, {year}"
    return None


def classify_operation(question: str, question_reasoning: str | None = None) -> str:
    """Classify a question into a compact operation family."""
    text = f"{question} {question_reasoning or ''}".lower()
    starts_with_binary = bool(
        re.match(r"^\s*(did|does|do|was|were|has|have|is|are|can|could|should|would)\b", text)
    )
    asks_for_numeric = any(
        phrase in text
        for phrase in (
            "how much",
            "what is",
            "what was",
            "what were",
            "what did",
            "what does",
            "what has",
            "year end",
            "at the end of",
            "in usd",
            "in units of percents",
            "amount of",
        )
    )

    # Computed ratios / margins
    if any(token in text for token in (
        "ratio", "margin", "as a percentage of", "return on equity",
        "return on assets", "roe", "roa", "current ratio",
        "debt to equity", "asset turnover",
    )):
        return "ratio"
    # Percentage changes / growth rates
    if any(token in text for token in (
        "growth rate",
        "cagr",
        "year-over-year change",
        "year over year change",
        "yoy change",
        "percentage change",
    )):
        return "percentage_change"
    # Existence checks
    if starts_with_binary and not asks_for_numeric and "?" in text:
        if any(token in text for token in ("whether ", "was there any", "did ", "does ", "has ", "have ")):
            return "existence"
    # Change detection
    if any(token in text for token in (
        "increase", "decrease", "difference", "change from",
        "changed from", "year over year", "year-over-year", "yoy",
    )):
        if "%" in text or "percent" in text or "percentage" in text:
            return "percentage_change"
        return "absolute_change"
    # Comparison
    if any(token in text for token in ("compare", "versus", "vs.", "trend", "across")):
        return "compare"
    # Narrative / qualitative
    if any(token in text for token in ("risk", "why", "explain", "discuss", "describe", "factor", "what are the", "what were the")):
        return "narrative"
    return "lookup"


def infer_answer_mode(question: str, operation: str) -> str:
    text = question.lower()
    if any(
        phrase in text
        for phrase in (
            "which segment",
            "which business",
            "which geographic",
            "which geography",
            "which product",
            "which category",
            "who are",
            "what are the geographies",
            "what are three main companies acquired",
            "which brought in the most",
            "what industry",
            "largest liability",
            "shareholder vote",
            "board member nominee",
        )
    ):
        return "entity_selection"
    if operation == "existence" or re.match(r"^\s*(did|does|was|were|has|have|is|are)\b", text):
        return "boolean"
    if operation in {
        "lookup",
        "absolute_change",
        "percentage_change",
        "ratio",
        "cagr",
        "ratio_avg_balance",
        "three_year_avg_ratio",
    }:
        return "formula" if any(
            phrase in text
            for phrase in (
                "calculate",
                "compute",
                "defined as",
                "using",
                "ratio",
                "margin",
                "turnover",
                "conversion",
                "capital-intensive",
                "capital intensive",
            )
        ) else "numeric_lookup"
    return "narrative"


def infer_time_scope(
    years: tuple[int, ...],
    quarters: tuple[QuarterRef, ...],
    as_of_date: str | None,
) -> str:
    if as_of_date:
        return "as_of_date"
    if quarters:
        return "quarter"
    if len(years) >= 2:
        return "multi_year"
    return "fy"


def infer_source_bias(question: str, answer_mode: str) -> str:
    text = question.lower()
    if any(
        phrase in text
        for phrase in (
            "agm",
            "shareholder proposal",
            "shareholder vote",
            "board member",
            "nominee",
            "proxy",
        )
    ):
        return "proxy"
    if any(
        phrase in text
        for phrase in (
            "guidance",
            "raised full year guidance",
            "expects",
            "outlook",
            "customer concentration",
            "ceo",
            "conference call",
        )
    ):
        return "earnings"
    if any(
        phrase in text
        for phrase in (
            "acquisition",
            "acquired",
            "spin off",
            "spinning off",
            "voting",
            "proposal",
            "revolving credit agreement",
            "separation",
            "congruency report",
        )
    ):
        return "8k_event"
    if answer_mode in {"entity_selection", "narrative"} and any(
        phrase in text
        for phrase in (
            "segment",
            "geograph",
            "customer",
            "industry",
            "what drove",
            "primary",
            "performed the best",
        )
    ):
        return "mda"
    return "financials"


def infer_answer_shape(question: str, answer_mode: str) -> str:
    text = question.lower()
    if answer_mode == "entity_selection":
        if any(phrase in text for phrase in ("which brought in the most", "highest net income", "lowest net revenue")):
            return "entity_with_value"
        return "entity"
    if answer_mode == "boolean":
        return "yes_no_with_reason"
    if answer_mode == "narrative":
        return "explanation"
    if "%" in text or "percent" in text:
        return "percent"
    return "number"


def infer_question_plan(
    question: str,
    known_metrics: list[str] | tuple[str, ...],
    *,
    question_reasoning: str | None = None,
) -> QuestionPlan:
    metrics = extract_metrics(question, known_metrics)
    years = extract_years(question)
    quarters = extract_quarters(question)
    as_of_date = extract_as_of_date(question)
    operation = classify_operation(question, question_reasoning)
    answer_mode = infer_answer_mode(question, operation)
    time_scope = infer_time_scope(years, quarters, as_of_date)
    source_bias = infer_source_bias(question, answer_mode)
    answer_shape = infer_answer_shape(question, answer_mode)
    quarter = quarters[0].period if quarters else None
    return QuestionPlan(
        operation=operation,
        metrics=metrics,
        answer_mode=answer_mode,
        time_scope=time_scope,
        answer_shape=answer_shape,
        source_bias=source_bias,
        quarter=quarter,
        as_of_date=as_of_date,
    )


def classify_route(
    operation: str,
    metrics: tuple[str, ...],
    question_type: str | None = None,
) -> str:
    """Classify the preferred answer route for a benchmark item."""
    if operation in {"lookup", "absolute_change", "percentage_change", "ratio", "existence"} and metrics:
        return "xbrl"
    if operation == "compare" and metrics:
        return "hybrid"
    if question_type and "table" in question_type.lower():
        return "xbrl"
    return "rag"


def extract_metrics(
    question: str,
    known_metrics: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    """Extract likely metric aliases from a question."""
    import re as _re
    q = question.lower()
    # Use word-boundary matching for known metrics to avoid false positives
    # like "cash" matching in "cash flow statement"
    # Short/ambiguous metrics need extra context checks
    _AMBIGUOUS_NEGATIVES = {
        "cash": r"\bcash\b(?!\s+flow)",  # "cash" but not "cash flow"
    }
    matches: set[str] = set()
    for metric in known_metrics:
        m_lower = metric.lower()
        if m_lower in _AMBIGUOUS_NEGATIVES:
            pattern = _AMBIGUOUS_NEGATIVES[m_lower]
        else:
            pattern = r"\b" + _re.escape(m_lower) + r"\b"
        if _re.search(pattern, q):
            matches.add(metric)

    heuristic_pairs = [
        # Cash flow
        ("capital expenditure", "capex"),
        ("capital expenditures", "capex"),
        ("cash from operations", "operating cash flow"),
        ("operating cash flow", "operating cash flow"),
        ("free cash flow", "free cash flow"),
        ("share repurchase", "share repurchase"),
        ("stock repurchase", "share repurchase"),
        # Balance sheet
        ("cash and cash equivalents", "cash"),
        ("total assets", "total assets"),
        ("total current assets", "total current assets"),
        ("total liabilities", "total liabilities"),
        ("total current liabilities", "total current liabilities"),
        ("stockholders' equity", "stockholders equity"),
        ("stockholders equity", "stockholders equity"),
        ("shareholders' equity", "stockholders equity"),
        ("accounts receivable", "accounts receivable"),
        ("accounts payable", "accounts payable"),
        ("goodwill", "goodwill"),
        ("inventory", "inventory"),
        ("inventories", "inventory"),
        ("long term debt", "long term debt"),
        ("property plant and equipment", "net ppe"),
        ("net pp&e", "net ppe"),
        ("net ppne", "net ppe"),
        ("ppne", "net ppe"),
        ("pp&e", "net ppe"),
        ("ppe", "net ppe"),
        ("retained earnings", "retained earnings"),
        ("intangible assets", "intangible assets"),
        # Income statement
        ("net income", "net income"),
        ("operating income", "operating income"),
        ("gross profit", "gross profit"),
        ("gross margin", "gross profit"),
        ("revenue", "revenue"),
        ("revenues", "revenue"),
        ("net sales", "revenue"),
        ("cost of revenue", "cost of revenue"),
        ("cost of goods sold", "cost of goods sold"),
        ("cogs", "cost of goods sold"),
        ("cost of sales", "cost of revenue"),
        ("research and development", "research and development"),
        ("r&d", "research and development"),
        ("selling general and administrative", "selling general and administrative"),
        ("sg&a", "sga"),
        ("sga", "sga"),
        ("income tax", "income tax"),
        ("interest expense", "interest expense"),
        ("depreciation", "depreciation"),
        # Per share
        ("eps", "eps"),
        ("earnings per share", "eps"),
        ("diluted eps", "diluted eps"),
        ("shares outstanding", "shares outstanding"),
        ("dividends per share", "dividends per share"),
        ("dividends", "dividends"),
    ]
    for phrase, alias in heuristic_pairs:
        if _re.search(r"\b" + _re.escape(phrase) + r"\b", q):
            matches.add(alias)

    # Formula-specific recovery for metrics-generated questions.
    formula_pairs = [
        ("fixed asset turnover", ("revenue", "net ppe")),
        ("operating cash flow ratio", ("operating cash flow", "total current liabilities")),
        ("working capital ratio", ("total current assets", "total current liabilities")),
        ("free cash flow", ("operating cash flow", "capex")),
        ("unadjusted ebitda", ("operating income", "depreciation")),
        ("ebitda", ("operating income", "depreciation")),
        ("dividend payout ratio", ("dividends", "net income")),
        ("retention ratio", ("dividends", "net income")),
        ("days payable outstanding", ("accounts payable", "inventory", "cost of goods sold")),
        ("dpo", ("accounts payable", "inventory", "cost of goods sold")),
        ("days sales outstanding", ("accounts receivable", "revenue")),
        ("dso", ("accounts receivable", "revenue")),
        ("days inventory outstanding", ("inventory", "cost of goods sold")),
        ("dio", ("inventory", "cost of goods sold")),
        ("cash conversion cycle", ("accounts payable", "accounts receivable", "inventory", "revenue", "cost of goods sold")),
        ("ccc", ("accounts payable", "accounts receivable", "inventory", "revenue", "cost of goods sold")),
    ]
    for phrase, aliases in formula_pairs:
        if phrase in q:
            matches.update(aliases)

    # Drop generic cash hits when the question is about cash flows or dividends.
    if "cash" in matches and (
        "cash flow" in q
        or "cash from operations" in q
        or "operating cash flow" in q
        or "cash dividends" in q
    ):
        matches.discard("cash")

    return tuple(sorted(matches))


def normalize_tuple(
    *,
    ticker: str,
    years: list[int] | tuple[int, ...],
    metrics: list[str] | tuple[str, ...],
    operation: str,
) -> NormalizedTuple:
    """Create a canonical tuple used for overlap checks."""
    clean_ticker = ticker.upper().strip()
    clean_years = tuple(sorted({int(year) for year in years}))
    clean_metrics = tuple(sorted({metric.strip().lower() for metric in metrics if metric}))
    clean_operation = operation.strip().lower()
    return NormalizedTuple(
        ticker=clean_ticker,
        years=clean_years,
        metrics=clean_metrics,
        operation=clean_operation,
    )


def financebench_row_to_manifest_entry(
    row: dict[str, Any],
    company_to_ticker: dict[str, str],
    known_metrics: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Convert a FinanceBench row into a benchmark governance manifest entry."""
    company = row["company"].strip()
    ticker = resolve_company_ticker(company, company_to_ticker)
    if ticker is None:
        ticker = str(row["doc_name"]).split("_", 1)[0].upper()

    years = extract_years(row.get("question"), row.get("doc_name"), row.get("doc_period"))
    metrics = extract_metrics(row.get("question", ""), known_metrics)
    operation = classify_operation(
        row.get("question", ""),
        row.get("question_reasoning"),
    )
    route = classify_route(operation, metrics, row.get("question_type"))
    tuple_obj = normalize_tuple(
        ticker=ticker,
        years=years,
        metrics=metrics,
        operation=operation,
    )

    return {
        "financebench_id": row["financebench_id"],
        "company": company,
        "ticker": ticker,
        "doc_name": row.get("doc_name"),
        "doc_period": row.get("doc_period"),
        "question_type": row.get("question_type"),
        "question_reasoning": row.get("question_reasoning"),
        "question": row.get("question"),
        "dataset_subset_label": row.get("dataset_subset_label"),
        "route_type": route,
        "eval_policy": "eval_only",
        "normalized_tuple": tuple_obj.to_dict(),
        "tuple_key": tuple_obj.to_key(),
    }


def manifest_tuple_keys(manifest_path: str | Path) -> set[str]:
    """Load tuple keys from a FinanceBench manifest."""
    path = Path(manifest_path)
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        records = data.get("questions", [])
    else:
        records = data
    return {
        entry["tuple_key"]
        for entry in records
        if entry.get("eval_policy") == "eval_only" and entry.get("tuple_key")
    }


def record_tuple_key(record: dict[str, Any]) -> str | None:
    """Extract a tuple key from a generated training record."""
    metadata = record.get("metadata") or {}
    tuple_data = metadata.get("normalized_tuple")
    if not tuple_data:
        return None
    return normalize_tuple(
        ticker=tuple_data["ticker"],
        years=tuple_data.get("years", []),
        metrics=tuple_data.get("metrics", []),
        operation=tuple_data.get("operation", ""),
    ).to_key()


def build_split_metadata(
    source: str,
    tuple_obj: NormalizedTuple | None = None,
) -> dict[str, Any]:
    """Build standard metadata for generated training records."""
    dataset_role = "train"
    split_bucket = None

    if tuple_obj is not None and source in {"xbrl_qa", "diff_summaries"}:
        split_bucket = stable_bucket(tuple_obj.to_key())
        if split_bucket < 10:
            dataset_role = "heldout_secqa_test"
        elif split_bucket < 20:
            dataset_role = "internal_secqa_dev"

    return {
        "source": source,
        "dataset_role": dataset_role,
        "normalized_tuple": tuple_obj.to_dict() if tuple_obj else None,
        "tuple_key": tuple_obj.to_key() if tuple_obj else None,
        "split_bucket": split_bucket,
    }
