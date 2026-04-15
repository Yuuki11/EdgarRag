"""
Training data preparation for FinEdgar Gemma 4 E2B fine-tuning.

Converts multiple financial NLP datasets into Gemma chat format JSONL files,
then combines and validates them for training.

Usage:
    python model/training/prepare_data.py --sources convfinqa,phrasebank
    python model/training/prepare_data.py --sources xbrl_qa
    python model/training/prepare_data.py --sources diff_summaries
    python model/training/prepare_data.py --combine
    python model/training/prepare_data.py --validate data/training/finedgar_train.jsonl
"""

import argparse
import difflib
import json
import os
import random
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRAINING_DIR = PROJECT_ROOT / "data" / "training"
BENCHMARK_MANIFEST_PATH = PROJECT_ROOT / "data" / "benchmarks" / "financebench" / "manifest.json"
MAX_PHRASEBANK_SHARE = 0.08

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.data.benchmarking import (
    build_split_metadata,
    infer_question_plan,
    manifest_tuple_keys,
    normalize_tuple,
)

TEACHER_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def teacher_ollama_generate_url() -> str:
    return f"{os.getenv('OLLAMA_HOST', TEACHER_OLLAMA_HOST).rstrip('/')}/api/generate"


def _ensure_training_dir():
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)


def _save_jsonl(records: list[dict], path: Path):
    """Write a list of dicts as newline-delimited JSON."""
    _ensure_training_dir()
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Saved {len(records)} examples to {path}")


def _build_record(
    user_content: str,
    assistant_content: str,
    *,
    source: str,
    tuple_obj=None,
    extra_metadata: dict | None = None,
) -> dict:
    metadata = build_split_metadata(source, tuple_obj=tuple_obj)
    question_plan = infer_question_plan(user_content, list(_get_metric_aliases().keys()))
    normalized_answer = assistant_content.strip().splitlines()[0].strip() if assistant_content.strip() else ""
    metadata.update(
        {
            "route": "xbrl" if source == "xbrl_qa" else "rag",
            "answer_mode": question_plan.answer_mode,
            "time_scope": question_plan.time_scope,
            "doc_type": "10-K" if source in {"xbrl_qa", "diff_summaries"} else "synthetic",
            "normalized_answer": normalized_answer,
            "answerability_label": "answerable" if normalized_answer and "cannot" not in normalized_answer.lower() else "abstain",
            "answer_shape": question_plan.answer_shape,
            "source_bias": question_plan.source_bias,
        }
    )
    if extra_metadata:
        metadata.update(extra_metadata)
    return {
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
        "metadata": metadata,
    }


def _call_local_teacher(prompt: str, model: str, timeout: float = 120.0) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 512},
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(teacher_ollama_generate_url(), json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except (httpx.HTTPError, httpx.TimeoutException):
        return ""


def annotate_records_with_local_teacher(records: list[dict], teacher_model: str) -> list[dict]:
    """Add optional local-teacher annotations for narrative/entity records."""
    for record in records:
        metadata = record.get("metadata") or {}
        if metadata.get("answer_mode") not in {"narrative", "entity_selection", "boolean"}:
            continue
        prompt = (
            "Label this SEC QA example. Return compact JSON with keys "
            "answerability, answer_shape, compressed_target.\n\n"
            f"Question:\n{record['messages'][0]['content']}\n\n"
            f"Reference answer:\n{record['messages'][1]['content']}\n"
        )
        raw = _call_local_teacher(prompt, teacher_model)
        if raw:
            metadata["teacher_model"] = teacher_model
            metadata["teacher_annotation"] = raw
    return records


def _load_eval_only_tuple_keys() -> set[str]:
    return manifest_tuple_keys(BENCHMARK_MANIFEST_PATH)


def _keep_record(tuple_obj, excluded_tuple_keys: set[str]) -> bool:
    if tuple_obj is None:
        return True
    return tuple_obj.to_key() not in excluded_tuple_keys


def _table_to_text(table: list[list[str]]) -> str:
    """Convert a list-of-lists table into a readable text table.

    Pads each column so values line up, separated by " | ".
    """
    if not table:
        return ""
    # Determine max width per column
    n_cols = max(len(row) for row in table)
    col_widths = [0] * n_cols
    for row in table:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    lines = []
    for idx, row in enumerate(table):
        padded = [str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)]
        # Pad missing columns
        for i in range(len(row), n_cols):
            padded.append(" " * col_widths[i])
        lines.append(" | ".join(padded))
        # Add separator after header row
        if idx == 0:
            lines.append("-+-".join("-" * w for w in col_widths))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source 1: ConvFinQA
# ---------------------------------------------------------------------------

def prepare_convfinqa() -> list[dict]:
    """Load ConvFinQA dataset and convert to Gemma chat format.

    - Loads from HuggingFace: MehdiHosseiniMoghadam/ConvFinQA
    - Filters to first-turn questions only (single-turn training)
    - Converts table to readable text
    - Target: ~3,000 examples
    """
    from datasets import load_dataset

    print("Loading ConvFinQA dataset...")
    ds = load_dataset("MehdiHosseiniMoghadam/ConvFinQA")

    records: list[dict] = []

    for split in ds:
        for example in ds[split]:
            table = example.get("table", example.get("table_ori", []))
            pre_text = example.get("pre_text", "")
            if isinstance(pre_text, list):
                pre_text = " ".join(pre_text)
            post_text = example.get("post_text", "")
            if isinstance(post_text, list):
                post_text = " ".join(post_text)

            # This dataset has flat fields: question, answer, steps
            question = example.get("question", "")
            if not question:
                continue

            answer = str(example.get("answer", ""))
            if not answer:
                continue

            # Steps is a list of dicts with arg1, arg2, op, res
            raw_steps = example.get("steps", [])
            if raw_steps and isinstance(raw_steps, list):
                step_parts = []
                for s in raw_steps:
                    if isinstance(s, dict):
                        step_parts.append(f"{s.get('op', '?')}({s.get('arg1', '?')}, {s.get('arg2', '?')}) = {s.get('res', '?')}")
                    else:
                        step_parts.append(str(s))
                steps = " → ".join(step_parts)
            else:
                steps = "Direct lookup from the provided data."

            table_text = _table_to_text(table)
            context_parts = []
            if table_text:
                context_parts.append(table_text)
            if pre_text:
                context_parts.append(pre_text)
            if post_text:
                context_parts.append(post_text)
            context = "\n".join(context_parts)

            user_content = (
                f"Given the following financial data:\n{context}\n\n"
                f"Question: {question}"
            )
            assistant_content = f"{answer}\n\nReasoning: {steps}"

            records.append(
                _build_record(
                    user_content,
                    assistant_content,
                    source="convfinqa",
                )
            )

    print(f"ConvFinQA: {len(records)} examples extracted")
    output_path = TRAINING_DIR / "convfinqa.jsonl"
    _save_jsonl(records, output_path)
    return records


# ---------------------------------------------------------------------------
# Source 2: Financial PhraseBank
# ---------------------------------------------------------------------------

# Template explanations keyed by sentiment label
_POSITIVE_EXPLANATIONS = [
    "it indicates improving financial performance",
    "it highlights growth in key business metrics",
    "it reflects strong operational results and positive momentum",
    "it signals revenue or profit expansion",
    "it describes favorable outcomes for the company",
    "it points to strengthening market position",
    "it conveys optimism about the company's financial trajectory",
    "it shows increased profitability or efficiency gains",
    "it emphasizes positive developments in the company's operations",
    "it describes upward trends in financial indicators",
    "it suggests the company is outperforming expectations",
    "it reflects a healthy financial outlook",
    "it highlights value creation for shareholders",
    "it indicates successful execution of business strategy",
    "it mentions improvements in margins or returns",
]

_NEGATIVE_EXPLANATIONS = [
    "it signals deteriorating financial conditions",
    "it indicates declining revenues or profitability",
    "it highlights losses or negative financial trends",
    "it reflects weakening operational performance",
    "it points to challenges facing the company's business",
    "it describes unfavorable changes in financial metrics",
    "it conveys concern about the company's financial health",
    "it shows reduced profitability or increasing costs",
    "it mentions restructuring, impairments, or write-downs",
    "it suggests the company is underperforming relative to expectations",
    "it reflects downward pressure on key financial indicators",
    "it describes contraction in business activity",
    "it indicates risk of financial distress or deterioration",
    "it highlights adverse developments in the company's market",
    "it points to shrinking margins or declining returns",
]

_NEUTRAL_EXPLANATIONS = [
    "it presents factual information without indicating positive or negative trends",
    "it describes a business event or transaction in objective terms",
    "it provides operational details without evaluative language",
    "it states financial figures without implying a directional trend",
    "it reports on corporate actions in a matter-of-fact manner",
    "it conveys information about business activities without sentiment",
    "it describes structural or organizational changes neutrally",
    "it presents market or industry data without a positive or negative slant",
    "it provides context about the company's operations without judgment",
    "it states factual details about the company's business activities",
    "it reports on routine corporate matters",
    "it describes business arrangements or agreements objectively",
    "it mentions financial events without indicating their impact as good or bad",
    "it relays factual details about transactions or filings",
    "it provides a straightforward account of corporate activities",
]

_LABEL_MAP = {0: "Negative", 1: "Neutral", 2: "Positive"}
_EXPLANATION_MAP = {
    0: _NEGATIVE_EXPLANATIONS,
    1: _NEUTRAL_EXPLANATIONS,
    2: _POSITIVE_EXPLANATIONS,
}


def prepare_phrasebank() -> list[dict]:
    """Load Financial PhraseBank (sentences_allagree) and convert to chat format.

    - Labels: 0=negative, 1=neutral, 2=positive
    - Generates template-based explanations per sentiment class
    - Target: ~4,840 examples
    """
    from datasets import load_dataset

    print("Loading Financial PhraseBank dataset...")
    ds = load_dataset("nickmuchi/financial-classification")

    records: list[dict] = []
    rng = random.Random(42)

    for split in ds:
        for example in ds[split]:
            sentence = example.get("sentence") or example.get("text", "")
            label_id = example.get("label") if "label" in example else example.get("labels", 1)

            label = _LABEL_MAP[label_id]
            explanation = rng.choice(_EXPLANATION_MAP[label_id])

            user_content = (
                "Classify the sentiment of this financial statement as positive, "
                "negative, or neutral. Explain your reasoning briefly.\n\n"
                f'"{sentence}"'
            )
            assistant_content = f"{label}\n\nThis statement is {label.lower()} because {explanation}."

            records.append(
                _build_record(
                    user_content,
                    assistant_content,
                    source="phrasebank",
                )
            )

    print(f"PhraseBank: {len(records)} examples extracted")
    output_path = TRAINING_DIR / "phrasebank.jsonl"
    _save_jsonl(records, output_path)
    return records


# ---------------------------------------------------------------------------
# Source 3: XBRL QA
# ---------------------------------------------------------------------------

# Template banks for XBRL QA pair generation

SIMPLE_TEMPLATES = [
    "What was {company}'s {metric} in FY{year}?",
    "How much did {company} report as {metric} for fiscal year {year}?",
    "According to {company}'s {year} 10-K filing, what was their {metric}?",
    "What is the {metric} figure from {company}'s FY{year} annual report?",
    "Report {company}'s {metric} for the fiscal year ending {year}.",
    "Can you tell me {company}'s {metric} as of FY{year}?",
    "What did {company} disclose as their {metric} in their FY{year} 10-K?",
]

YOY_TEMPLATES = [
    "How did {company}'s {metric} change from FY{y1} to FY{y2}?",
    "What was the year-over-year change in {company}'s {metric} between {y1} and {y2}?",
    "Compare {company}'s {metric} in FY{y1} versus FY{y2}.",
    "By how much did {company}'s {metric} increase or decrease from FY{y1} to FY{y2}?",
    "Describe the trend in {company}'s {metric} from fiscal year {y1} to {y2}.",
    "What was the difference in {company}'s {metric} between their FY{y1} and FY{y2} 10-K filings?",
]

RATIO_TEMPLATES = [
    "What was {company}'s {ratio_name} in FY{year}?",
    "Calculate {company}'s {ratio_name} for fiscal year {year}.",
    "Based on {company}'s FY{year} 10-K, what was their {ratio_name}?",
    "Report {company}'s {ratio_name} as of FY{year}.",
    "What {ratio_name} did {company} have in FY{year}?",
]

FORMULA_TEMPLATES = {
    "fixed_asset_turnover": [
        "What was {company}'s fixed asset turnover in FY{end_year}? Use FY{end_year} revenue divided by average PP&E between FY{start_year} and FY{end_year}.",
        "Calculate {company}'s FY{end_year} fixed asset turnover ratio using revenue / average PP&E across FY{start_year}-FY{end_year}.",
    ],
    "roa_avg_assets": [
        "What was {company}'s return on assets in FY{end_year}? Define ROA as FY{end_year} net income divided by average total assets between FY{start_year} and FY{end_year}.",
        "Compute FY{end_year} ROA for {company} using net income / average assets across FY{start_year} and FY{end_year}.",
    ],
    "dpo": [
        "What was {company}'s FY{end_year} days payable outstanding (DPO)? Use 365 * average accounts payable between FY{start_year} and FY{end_year} divided by FY{end_year} COGS plus the inventory change.",
        "Calculate FY{end_year} DPO for {company} using average AP / (COGS + change in inventory).",
    ],
    "ccc": [
        "What was {company}'s FY{end_year} cash conversion cycle (CCC)? Use DIO + DSO - DPO with FY{end_year} statement values and averages from FY{start_year} to FY{end_year}.",
        "Compute {company}'s FY{end_year} cash conversion cycle using DIO, DSO, and DPO built from FY{start_year}-FY{end_year} balance-sheet and income-statement values.",
    ],
    "three_year_capex_margin": [
        "What was {company}'s FY{start_year}-FY{end_year} three-year average capex as a percentage of revenue?",
        "Calculate the three-year average of capex / revenue for {company} from FY{start_year} to FY{end_year}.",
    ],
    "ebitda_margin": [
        "What was {company}'s FY{year} unadjusted EBITDA margin? Define EBITDA as operating income plus depreciation and amortization, then divide by revenue.",
        "Compute {company}'s FY{year} EBITDA margin using (operating income + depreciation) / revenue.",
    ],
    "retention_ratio": [
        "What was {company}'s FY{year} retention ratio using total cash dividends paid and net income?",
        "Calculate FY{year} retention ratio for {company} as 1 - dividends / net income.",
    ],
}

COMPARE_TEMPLATES = [
    "Compare {company}'s {metric} across FY{y1}, FY{y2}, and FY{y3}.",
    "How did {company}'s {metric} trend over FY{y1}, FY{y2}, and FY{y3}?",
    "Summarize the change in {company}'s {metric} from FY{y1} through FY{y3}.",
]

EXISTENCE_TEMPLATES = [
    "Did {company} report {metric} in FY{year}?",
    "Was {metric} disclosed by {company} in its FY{year} 10-K?",
    "Does {company}'s FY{year} filing include a value for {metric}?",
]

ABSTENTION_TEMPLATES = [
    "What was {company}'s crypto treasury value in FY{year}?",
    "Report {company}'s water usage liability in FY{year}.",
    "How much did {company} disclose as metaverse restructuring costs in FY{year}?",
]

# Ratio definitions: (friendly name, numerator_metric, denominator_metric)
RATIO_DEFINITIONS = [
    ("debt-to-equity ratio", "total liabilities", "stockholders equity"),
    ("gross margin", "gross profit", "revenue"),
    ("operating margin", "operating income", "revenue"),
    ("net profit margin", "net income", "revenue"),
    ("R&D-to-revenue ratio", "research and development", "revenue"),
    ("SGA-to-revenue ratio", "selling general and administrative", "revenue"),
    ("current ratio", "total current assets", "total current liabilities"),
    ("return on equity", "net income", "stockholders equity"),
    ("return on assets", "net income", "total assets"),
    ("asset turnover ratio", "revenue", "total assets"),
]

# Metrics to use for simple and YoY QA pairs
SIMPLE_METRICS = [
    "revenue",
    "net income",
    "total assets",
    "total liabilities",
    "stockholders equity",
    "operating income",
    "cash",
    "cost of revenue",
    "gross profit",
    "research and development",
    "long term debt",
    "eps",
    # Expanded metrics
    "total current assets",
    "total current liabilities",
    "accounts receivable",
    "inventory",
    "goodwill",
    "net ppe",
    "capex",
    "operating cash flow",
    "selling general and administrative",
    "interest expense",
    "depreciation",
    "income tax",
    "dividends",
    "shares outstanding",
    "retained earnings",
    "diluted eps",
    "short term debt",
]

EXISTENCE_METRICS = [
    "revenue",
    "net income",
    "research and development",
    "long term debt",
    "shares outstanding",
    "goodwill",
    "accounts receivable",
    "inventory",
    "dividends",
]


def _format_dollar(value: float, unit: str) -> str:
    """Format a numeric value with $ signs and commas, choosing appropriate scale."""
    if unit == "USD/shares":
        return f"${value:,.2f} per share"
    if unit == "shares":
        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:,.2f} billion shares"
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:,.1f} million shares"
        return f"{value:,.0f} shares"
    # USD
    abs_val = abs(value)
    if abs_val >= 1_000_000_000:
        formatted = f"${value / 1_000_000_000:,.2f} billion"
    elif abs_val >= 1_000_000:
        formatted = f"${value / 1_000_000:,.1f} million"
    else:
        formatted = f"${value:,.0f}"
    return formatted


def _load_xbrl_cache(ticker: str) -> dict | None:
    """Load XBRL cache file for a ticker, return None if not found."""
    cache_path = PROJECT_ROOT / "data" / "xbrl_cache" / f"{ticker.upper()}.json"
    if not cache_path.exists():
        return None
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_metric_aliases() -> dict[str, list[str]]:
    """Lazy-load METRIC_ALIASES from backend.data.xbrl_fetcher."""
    if not hasattr(_get_metric_aliases, "_cache"):
        _proj = str(PROJECT_ROOT)
        if _proj not in sys.path:
            sys.path.insert(0, _proj)
        from backend.data.xbrl_fetcher import METRIC_ALIASES
        _get_metric_aliases._cache = METRIC_ALIASES
    return _get_metric_aliases._cache


def _get_metric_from_cache(
    data: dict, concept: str, year: int, period: str = "FY"
) -> tuple[str, float, str] | None:
    """Extract a metric from cached XBRL data.

    Returns (concept_name, value, unit) or None.
    Uses METRIC_ALIASES to resolve friendly names.
    """
    aliases = _get_metric_aliases()
    concept_lower = concept.lower()
    if concept_lower in aliases:
        concepts_to_try = aliases[concept_lower]
    else:
        concepts_to_try = [concept]

    us_gaap = data.get("facts", {}).get("us-gaap", {})
    target_form = "10-K" if period == "FY" else "10-Q"

    for concept_name in concepts_to_try:
        concept_data = us_gaap.get(concept_name)
        if concept_data is None:
            continue

        units = concept_data.get("units", {})
        for unit_key in ("USD", "USD/shares", "shares", "pure"):
            entries = units.get(unit_key)
            if entries is None:
                continue

            for entry in entries:
                if (
                    entry.get("fy") == year
                    and entry.get("fp") == period
                    and entry.get("form") == target_form
                ):
                    return (concept_name, entry["val"], unit_key)

    return None


def _available_fy_years(data: dict) -> list[int]:
    """Get all fiscal years that have 10-K data in a cached XBRL dataset."""
    years = set()
    us_gaap = data.get("facts", {}).get("us-gaap", {})
    # Sample a few common concepts to find available years
    for concept_name in ["Revenues", "Assets", "NetIncomeLoss",
                         "RevenueFromContractWithCustomerExcludingAssessedTax"]:
        concept_data = us_gaap.get(concept_name)
        if concept_data is None:
            continue
        for unit_key, entries in concept_data.get("units", {}).items():
            for entry in entries:
                if entry.get("form") == "10-K" and entry.get("fp") == "FY":
                    fy = entry.get("fy")
                    if fy and 2018 <= fy <= 2025:
                        years.add(fy)
    return sorted(years)


def _format_ratio(value: float, *, as_percent: bool = False, decimals: int = 2) -> str:
    if as_percent:
        return f"{value * 100:.{decimals}f}%"
    return f"{value:.{decimals}f}"


def _append_formula_record(
    records: list[dict],
    *,
    rng: random.Random,
    excluded_tuple_keys: set[str],
    ticker: str,
    company_name: str,
    years: list[int],
    metrics: list[str],
    operation: str,
    question: str,
    answer: str,
) -> bool:
    tuple_obj = normalize_tuple(
        ticker=ticker,
        years=years,
        metrics=metrics,
        operation=operation,
    )
    if not _keep_record(tuple_obj, excluded_tuple_keys):
        return False
    records.append(
        _build_record(
            question,
            answer,
            source="xbrl_qa",
            tuple_obj=tuple_obj,
            extra_metadata={"company": company_name},
        )
    )
    return True


def prepare_xbrl_qa(companies_json_path: str = "data/companies.json") -> list[dict]:
    """Generate QA pairs from XBRL data using templates.

    Loads cached XBRL data and generates benchmark-safe SEC QA covering
    lookups, absolute/percentage change, ratios, comparisons, existence
    checks, and abstention examples.
    """
    companies_path = PROJECT_ROOT / companies_json_path
    with open(companies_path, "r", encoding="utf-8") as f:
        companies = json.load(f)

    rng = random.Random(42)
    records: list[dict] = []
    excluded_tuple_keys = _load_eval_only_tuple_keys()
    skipped_for_leakage = 0

    for company in companies:
        ticker = company["ticker"]
        name = company["name"]

        data = _load_xbrl_cache(ticker)
        if data is None:
            continue

        years = _available_fy_years(data)
        if not years:
            continue

        # --- Simple lookup pairs ---
        for year in years:
            for metric in SIMPLE_METRICS:
                result = _get_metric_from_cache(data, metric, year)
                if result is None:
                    continue

                concept_name, value, unit = result
                template = rng.choice(SIMPLE_TEMPLATES)
                question = template.format(company=name, metric=metric, year=year)
                tuple_obj = normalize_tuple(
                    ticker=ticker,
                    years=[year],
                    metrics=[metric],
                    operation="lookup",
                )
                if not _keep_record(tuple_obj, excluded_tuple_keys):
                    skipped_for_leakage += 1
                    continue

                formatted_val = _format_dollar(value, unit)
                answer = (
                    f"{name}'s {metric} in FY{year} was {formatted_val}, "
                    f"as reported in their FY{year} 10-K filing ({concept_name})."
                )

                records.append(
                    _build_record(
                        question,
                        answer,
                        source="xbrl_qa",
                        tuple_obj=tuple_obj,
                        extra_metadata={"company": name},
                    )
                )

        # --- Year-over-year pairs ---
        for i in range(len(years) - 1):
            y1, y2 = years[i], years[i + 1]
            for metric in SIMPLE_METRICS:
                r1 = _get_metric_from_cache(data, metric, y1)
                r2 = _get_metric_from_cache(data, metric, y2)
                if r1 is None or r2 is None:
                    continue

                _, val1, unit1 = r1
                concept_name, val2, unit2 = r2

                template = rng.choice(YOY_TEMPLATES)
                question = template.format(company=name, metric=metric, y1=y1, y2=y2)
                fv1 = _format_dollar(val1, unit1)
                fv2 = _format_dollar(val2, unit2)

                abs_tuple = normalize_tuple(
                    ticker=ticker,
                    years=[y1, y2],
                    metrics=[metric],
                    operation="absolute_change",
                )
                if _keep_record(abs_tuple, excluded_tuple_keys):
                    delta = val2 - val1
                    answer = (
                        f"{name}'s {metric} changed by {_format_dollar(delta, unit2)} "
                        f"from FY{y1} to FY{y2}, moving from {fv1} to {fv2}. "
                        f"(Source concepts: {concept_name})"
                    )
                    records.append(
                        _build_record(
                            question,
                            answer,
                            source="xbrl_qa",
                            tuple_obj=abs_tuple,
                            extra_metadata={"company": name},
                        )
                    )
                else:
                    skipped_for_leakage += 1

                pct_tuple = normalize_tuple(
                    ticker=ticker,
                    years=[y1, y2],
                    metrics=[metric],
                    operation="percentage_change",
                )
                if val1 != 0 and _keep_record(pct_tuple, excluded_tuple_keys):
                    pct_change = ((val2 - val1) / abs(val1)) * 100
                    direction = "increase" if pct_change >= 0 else "decrease"
                    pct_question = (
                        f"What was the percentage change in {name}'s {metric} "
                        f"from FY{y1} to FY{y2}?"
                    )
                    pct_answer = (
                        f"The percentage change in {name}'s {metric} from FY{y1} "
                        f"to FY{y2} was {pct_change:+.2f}% ({direction}), based on "
                        f"{fv1} and {fv2}. (Source concept: {concept_name})"
                    )
                    records.append(
                        _build_record(
                            pct_question,
                            pct_answer,
                            source="xbrl_qa",
                            tuple_obj=pct_tuple,
                            extra_metadata={"company": name},
                        )
                    )
                elif val1 != 0:
                    skipped_for_leakage += 1

        # --- Ratio pairs ---
        for year in years:
            for ratio_name, num_metric, den_metric in RATIO_DEFINITIONS:
                r_num = _get_metric_from_cache(data, num_metric, year)
                r_den = _get_metric_from_cache(data, den_metric, year)
                if r_num is None or r_den is None:
                    continue

                _, num_val, num_unit = r_num
                _, den_val, den_unit = r_den
                if den_val == 0:
                    continue

                ratio_val = num_val / den_val

                template = rng.choice(RATIO_TEMPLATES)
                question = template.format(
                    company=name, ratio_name=ratio_name, year=year
                )
                tuple_obj = normalize_tuple(
                    ticker=ticker,
                    years=[year],
                    metrics=[num_metric, den_metric],
                    operation="ratio",
                )
                if not _keep_record(tuple_obj, excluded_tuple_keys):
                    skipped_for_leakage += 1
                    continue

                fnum = _format_dollar(num_val, num_unit)
                fden = _format_dollar(den_val, den_unit)

                # Format ratio appropriately
                if "margin" in ratio_name or "ratio" in ratio_name.lower():
                    if abs(ratio_val) < 10:
                        ratio_str = f"{ratio_val:.2f}"
                    else:
                        ratio_str = f"{ratio_val:.1f}"
                    if "margin" in ratio_name:
                        ratio_str = f"{ratio_val * 100:.1f}%"
                else:
                    ratio_str = f"{ratio_val:.2f}"

                answer = (
                    f"{name}'s {ratio_name} in FY{year} was {ratio_str}, "
                    f"calculated as {num_metric} ({fnum}) divided by "
                    f"{den_metric} ({fden}). "
                    f"(Source: FY{year} 10-K filing)"
                )

                records.append(
                    _build_record(
                        question,
                        answer,
                        source="xbrl_qa",
                        tuple_obj=tuple_obj,
                        extra_metadata={"company": name},
                    )
                )

        # --- Formula-heavy SEC-style QA ---
        for i in range(len(years) - 1):
            y1, y2 = years[i], years[i + 1]

            revenue_y2 = _get_metric_from_cache(data, "revenue", y2)
            ppe_y1 = _get_metric_from_cache(data, "net ppe", y1)
            ppe_y2 = _get_metric_from_cache(data, "net ppe", y2)
            if revenue_y2 and ppe_y1 and ppe_y2 and (ppe_y1[1] + ppe_y2[1]) != 0:
                ratio_val = revenue_y2[1] / ((ppe_y1[1] + ppe_y2[1]) / 2.0)
                question = rng.choice(FORMULA_TEMPLATES["fixed_asset_turnover"]).format(
                    company=name, start_year=y1, end_year=y2
                )
                answer = (
                    f"{name}'s fixed asset turnover in FY{y2} was {_format_ratio(ratio_val)}. "
                    f"It was calculated as revenue {_format_dollar(revenue_y2[1], revenue_y2[2])} "
                    f"divided by average PP&E of "
                    f"{_format_dollar((ppe_y1[1] + ppe_y2[1]) / 2.0, ppe_y2[2])}."
                )
                if not _append_formula_record(
                    records,
                    rng=rng,
                    excluded_tuple_keys=excluded_tuple_keys,
                    ticker=ticker,
                    company_name=name,
                    years=[y1, y2],
                    metrics=["revenue", "net ppe"],
                    operation="ratio",
                    question=question,
                    answer=answer,
                ):
                    skipped_for_leakage += 1

            net_income_y2 = _get_metric_from_cache(data, "net income", y2)
            assets_y1 = _get_metric_from_cache(data, "total assets", y1)
            assets_y2 = _get_metric_from_cache(data, "total assets", y2)
            if net_income_y2 and assets_y1 and assets_y2 and (assets_y1[1] + assets_y2[1]) != 0:
                roa_val = net_income_y2[1] / ((assets_y1[1] + assets_y2[1]) / 2.0)
                question = rng.choice(FORMULA_TEMPLATES["roa_avg_assets"]).format(
                    company=name, start_year=y1, end_year=y2
                )
                answer = (
                    f"{name}'s FY{y2} ROA was {_format_ratio(roa_val, as_percent=True)}. "
                    f"The formula used net income {_format_dollar(net_income_y2[1], net_income_y2[2])} "
                    f"over average assets {_format_dollar((assets_y1[1] + assets_y2[1]) / 2.0, assets_y2[2])}."
                )
                if not _append_formula_record(
                    records,
                    rng=rng,
                    excluded_tuple_keys=excluded_tuple_keys,
                    ticker=ticker,
                    company_name=name,
                    years=[y1, y2],
                    metrics=["net income", "total assets"],
                    operation="ratio",
                    question=question,
                    answer=answer,
                ):
                    skipped_for_leakage += 1

            ap_y1 = _get_metric_from_cache(data, "accounts payable", y1)
            ap_y2 = _get_metric_from_cache(data, "accounts payable", y2)
            inv_y1 = _get_metric_from_cache(data, "inventory", y1)
            inv_y2 = _get_metric_from_cache(data, "inventory", y2)
            cogs_y2 = _get_metric_from_cache(data, "cost of goods sold", y2)
            revenue_y1 = _get_metric_from_cache(data, "revenue", y1)
            ar_y1 = _get_metric_from_cache(data, "accounts receivable", y1)
            ar_y2 = _get_metric_from_cache(data, "accounts receivable", y2)
            if ap_y1 and ap_y2 and inv_y1 and inv_y2 and cogs_y2:
                denominator = cogs_y2[1] + (inv_y2[1] - inv_y1[1])
                if denominator:
                    dpo_val = 365.0 * ((ap_y1[1] + ap_y2[1]) / 2.0) / denominator
                    question = rng.choice(FORMULA_TEMPLATES["dpo"]).format(
                        company=name, start_year=y1, end_year=y2
                    )
                    answer = (
                        f"{name}'s FY{y2} DPO was {dpo_val:.2f}. "
                        f"It used average accounts payable divided by FY{y2} COGS plus inventory change."
                    )
                    if not _append_formula_record(
                        records,
                        rng=rng,
                        excluded_tuple_keys=excluded_tuple_keys,
                        ticker=ticker,
                        company_name=name,
                        years=[y1, y2],
                        metrics=["accounts payable", "inventory", "cost of goods sold"],
                        operation="lookup",
                        question=question,
                        answer=answer,
                    ):
                        skipped_for_leakage += 1

            if all(item is not None for item in (ap_y1, ap_y2, inv_y1, inv_y2, cogs_y2, revenue_y2, ar_y1, ar_y2)):
                dpo_den = cogs_y2[1] + (inv_y2[1] - inv_y1[1])
                if dpo_den and cogs_y2[1] and revenue_y2[1]:
                    dpo_val = 365.0 * ((ap_y1[1] + ap_y2[1]) / 2.0) / dpo_den
                    dio_val = 365.0 * ((inv_y1[1] + inv_y2[1]) / 2.0) / cogs_y2[1]
                    dso_val = 365.0 * ((ar_y1[1] + ar_y2[1]) / 2.0) / revenue_y2[1]
                    ccc_val = dio_val + dso_val - dpo_val
                    question = rng.choice(FORMULA_TEMPLATES["ccc"]).format(
                        company=name, start_year=y1, end_year=y2
                    )
                    answer = (
                        f"{name}'s FY{y2} cash conversion cycle was {ccc_val:.2f}. "
                        f"DIO was {dio_val:.2f}, DSO was {dso_val:.2f}, and DPO was {dpo_val:.2f}."
                    )
                    if not _append_formula_record(
                        records,
                        rng=rng,
                        excluded_tuple_keys=excluded_tuple_keys,
                        ticker=ticker,
                        company_name=name,
                        years=[y1, y2],
                        metrics=["accounts payable", "accounts receivable", "inventory", "revenue", "cost of goods sold"],
                        operation="lookup",
                        question=question,
                        answer=answer,
                    ):
                        skipped_for_leakage += 1

        if len(years) >= 3:
            for idx in range(len(years) - 2):
                y1, y2, y3 = years[idx], years[idx + 1], years[idx + 2]
                capex_vals = [_get_metric_from_cache(data, "capex", y) for y in (y1, y2, y3)]
                revenue_vals = [_get_metric_from_cache(data, "revenue", y) for y in (y1, y2, y3)]
                if all(v is not None for v in capex_vals) and all(v is not None for v in revenue_vals):
                    ratios = [capex_vals[i][1] / revenue_vals[i][1] for i in range(3) if revenue_vals[i][1]]
                    if len(ratios) == 3:
                        avg_ratio = sum(ratios) / 3.0
                        question = rng.choice(FORMULA_TEMPLATES["three_year_capex_margin"]).format(
                            company=name, start_year=y1, end_year=y3
                        )
                        answer = (
                            f"{name}'s three-year average capex as a percentage of revenue from FY{y1} to FY{y3} "
                            f"was {_format_ratio(avg_ratio, as_percent=True)}."
                        )
                        if not _append_formula_record(
                            records,
                            rng=rng,
                            excluded_tuple_keys=excluded_tuple_keys,
                            ticker=ticker,
                            company_name=name,
                            years=[y1, y2, y3],
                            metrics=["capex", "revenue"],
                            operation="ratio",
                            question=question,
                            answer=answer,
                        ):
                            skipped_for_leakage += 1

        for year in years:
            op_income = _get_metric_from_cache(data, "operating income", year)
            depreciation = _get_metric_from_cache(data, "depreciation", year)
            revenue = _get_metric_from_cache(data, "revenue", year)
            dividends = _get_metric_from_cache(data, "dividends", year)
            net_income = _get_metric_from_cache(data, "net income", year)

            if op_income and depreciation and revenue and revenue[1]:
                ebitda_val = op_income[1] + depreciation[1]
                margin_val = ebitda_val / revenue[1]
                question = rng.choice(FORMULA_TEMPLATES["ebitda_margin"]).format(
                    company=name, year=year
                )
                answer = (
                    f"{name}'s FY{year} EBITDA margin was {_format_ratio(margin_val, as_percent=True)}. "
                    f"EBITDA was {_format_dollar(ebitda_val, op_income[2])}, computed as operating income plus depreciation."
                )
                if not _append_formula_record(
                    records,
                    rng=rng,
                    excluded_tuple_keys=excluded_tuple_keys,
                    ticker=ticker,
                    company_name=name,
                    years=[year],
                    metrics=["operating income", "depreciation", "revenue"],
                    operation="ratio",
                    question=question,
                    answer=answer,
                ):
                    skipped_for_leakage += 1

            if dividends and net_income and net_income[1]:
                retention_val = 1.0 - (dividends[1] / net_income[1])
                question = rng.choice(FORMULA_TEMPLATES["retention_ratio"]).format(
                    company=name, year=year
                )
                answer = (
                    f"{name}'s FY{year} retention ratio was {_format_ratio(retention_val)}. "
                    f"It was calculated as 1 - dividends {_format_dollar(dividends[1], dividends[2])} "
                    f"/ net income {_format_dollar(net_income[1], net_income[2])}."
                )
                if not _append_formula_record(
                    records,
                    rng=rng,
                    excluded_tuple_keys=excluded_tuple_keys,
                    ticker=ticker,
                    company_name=name,
                    years=[year],
                    metrics=["dividends", "net income"],
                    operation="ratio",
                    question=question,
                    answer=answer,
                ):
                    skipped_for_leakage += 1

        # --- Three-year comparisons ---
        if len(years) >= 3:
            for idx in range(len(years) - 2):
                y1, y2, y3 = years[idx], years[idx + 1], years[idx + 2]
                for metric in SIMPLE_METRICS[:8]:
                    facts = [
                        _get_metric_from_cache(data, metric, year)
                        for year in (y1, y2, y3)
                    ]
                    if any(fact is None for fact in facts):
                        continue
                    tuple_obj = normalize_tuple(
                        ticker=ticker,
                        years=[y1, y2, y3],
                        metrics=[metric],
                        operation="compare",
                    )
                    if not _keep_record(tuple_obj, excluded_tuple_keys):
                        skipped_for_leakage += 1
                        continue

                    formatted = [
                        _format_dollar(fact[1], fact[2])
                        for fact in facts
                    ]
                    question = rng.choice(COMPARE_TEMPLATES).format(
                        company=name,
                        metric=metric,
                        y1=y1,
                        y2=y2,
                        y3=y3,
                    )
                    answer = (
                        f"{name}'s {metric} was {formatted[0]} in FY{y1}, "
                        f"{formatted[1]} in FY{y2}, and {formatted[2]} in FY{y3}. "
                        f"This provides a three-year comparison without relying on benchmark-specific phrasing."
                    )
                    records.append(
                        _build_record(
                            question,
                            answer,
                            source="xbrl_qa",
                            tuple_obj=tuple_obj,
                            extra_metadata={"company": name},
                        )
                    )

        # --- Existence and abstention pairs ---
        for year in years:
            for metric in EXISTENCE_METRICS:
                exists = _get_metric_from_cache(data, metric, year) is not None
                tuple_obj = normalize_tuple(
                    ticker=ticker,
                    years=[year],
                    metrics=[metric],
                    operation="existence",
                )
                if not _keep_record(tuple_obj, excluded_tuple_keys):
                    skipped_for_leakage += 1
                    continue

                question = rng.choice(EXISTENCE_TEMPLATES).format(
                    company=name,
                    metric=metric,
                    year=year,
                )
                answer = (
                    f"Yes, {name} reported {metric} in FY{year}."
                    if exists
                    else f"No, a FY{year} XBRL fact for {metric} was not found for {name}."
                )
                records.append(
                    _build_record(
                        question,
                        answer,
                        source="xbrl_qa",
                        tuple_obj=tuple_obj,
                        extra_metadata={"company": name},
                    )
                )

            unsupported_metric = "crypto treasury value"
            abstain_tuple = normalize_tuple(
                ticker=ticker,
                years=[year],
                metrics=[unsupported_metric],
                operation="lookup",
            )
            if _keep_record(abstain_tuple, excluded_tuple_keys):
                abstain_question = rng.choice(ABSTENTION_TEMPLATES).format(
                    company=name,
                    year=year,
                )
                abstain_answer = (
                    f"I cannot determine that from the available FY{year} SEC XBRL facts "
                    f"for {name}. No matching structured metric was found, so the system "
                    f"should abstain rather than guess."
                )
                records.append(
                    _build_record(
                        abstain_question,
                        abstain_answer,
                        source="xbrl_qa",
                        tuple_obj=abstain_tuple,
                        extra_metadata={"company": name, "abstention_example": True},
                    )
                )

    # Shuffle and cap at a reasonable size
    rng.shuffle(records)
    if len(records) > 2600:
        records = records[:2600]

    print(
        f"XBRL QA: {len(records)} examples generated "
        f"({skipped_for_leakage} skipped due to eval-only tuple overlap)"
    )
    output_path = TRAINING_DIR / "xbrl_qa.jsonl"
    _save_jsonl(records, output_path)
    return records


# ---------------------------------------------------------------------------
# Source 4: Diff Summaries (Phase A — template-based)
# ---------------------------------------------------------------------------

PARSED_DIR = PROJECT_ROOT / "data" / "parsed"

# Section friendly names for templates
_SECTION_FRIENDLY_NAMES = {
    "item_1": "Business",
    "item_1a": "Risk Factors",
    "item_7": "Management's Discussion and Analysis",
    "item_7a": "Quantitative and Qualitative Disclosures About Market Risk",
    "item_8": "Financial Statements and Supplementary Data",
}

_DIFF_SUMMARY_TEMPLATES = [
    (
        "The {section_name} section of {company}'s 10-K changed by approximately "
        "{pct:.0f}% between FY{y1} and FY{y2}. {added_str}{removed_str}"
    ),
    (
        "Between FY{y1} and FY{y2}, {company}'s {section_name} section was "
        "{change_desc}. {added_str}{removed_str}"
    ),
    (
        "Comparing {company}'s {section_name} in their FY{y1} and FY{y2} 10-K filings, "
        "the section changed by about {pct:.0f}%. {added_str}{removed_str}"
    ),
    (
        "{company} {change_verb} their {section_name} section between FY{y1} and "
        "FY{y2}, with an overall change of approximately {pct:.0f}%. {added_str}{removed_str}"
    ),
    (
        "In {company}'s FY{y2} 10-K filing, the {section_name} section differs from "
        "FY{y1} by approximately {pct:.0f}%. {added_str}{removed_str}"
    ),
]

_DIFF_QUESTION_TEMPLATES = [
    "How did {company}'s {section_name} section change between their FY{y1} and FY{y2} 10-K filings?",
    "What are the key differences in {company}'s {section_name} between FY{y1} and FY{y2}?",
    "Summarize the changes in the {section_name} section of {company}'s 10-K filing from FY{y1} to FY{y2}.",
    "Compare the {section_name} section in {company}'s FY{y1} and FY{y2} annual reports.",
    "What changed in {company}'s {section_name} disclosure from FY{y1} to FY{y2}?",
]


def _split_paragraphs(text: str) -> list[str]:
    """Split section text into paragraphs, filtering out very short ones."""
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    # Also split on single newlines if paragraphs are too few
    if len(paragraphs) <= 1 and text:
        paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 50]
    return paragraphs


def _compute_paragraph_diff(
    paras_old: list[str], paras_new: list[str]
) -> tuple[float, int, int, int]:
    """Compute paragraph-level diff stats.

    Returns (change_pct, n_added, n_removed, n_changed).
    """
    matcher = difflib.SequenceMatcher(None, paras_old, paras_new)
    ratio = matcher.ratio()  # 1.0 = identical, 0.0 = completely different
    change_pct = (1.0 - ratio) * 100

    n_added = 0
    n_removed = 0
    n_changed = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            n_added += j2 - j1
        elif tag == "delete":
            n_removed += i2 - i1
        elif tag == "replace":
            n_changed += max(i2 - i1, j2 - j1)

    return change_pct, n_added, n_removed, n_changed


def _extract_topic_hint(paragraph: str, max_words: int = 8) -> str:
    """Extract a brief topic hint from the start of a paragraph."""
    words = paragraph.split()
    snippet = " ".join(words[:max_words])
    if len(words) > max_words:
        snippet += "..."
    return snippet


def prepare_diff_summaries() -> list[dict]:
    """Generate training data for filing diff summarization (Phase A).

    Uses difflib.SequenceMatcher for paragraph-level diffs between
    consecutive year sections. Generates structured summaries using
    templates. Targets 60-80 pairs.
    """
    # Load companies.json to get name mapping
    companies_path = PROJECT_ROOT / "data" / "companies.json"
    with open(companies_path, "r", encoding="utf-8") as f:
        companies = json.load(f)
    ticker_to_name = {c["ticker"]: c["name"] for c in companies}

    rng = random.Random(42)
    records: list[dict] = []

    if not PARSED_DIR.exists():
        print("No parsed data directory found — skipping diff summaries.")
        return records

    # Iterate over parsed companies
    for ticker_dir in sorted(PARSED_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name
        company_name = ticker_to_name.get(ticker, ticker)

        # Get available years (sorted)
        year_dirs = sorted(
            [d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()],
            key=lambda d: int(d.name),
        )

        # Need at least 2 consecutive years
        if len(year_dirs) < 2:
            continue

        # Iterate over consecutive year pairs
        for idx in range(len(year_dirs) - 1):
            y1_dir = year_dirs[idx]
            y2_dir = year_dirs[idx + 1]
            y1 = int(y1_dir.name)
            y2 = int(y2_dir.name)

            # Load sections for both years
            s1_path = y1_dir / "sections.json"
            s2_path = y2_dir / "sections.json"
            if not s1_path.exists() or not s2_path.exists():
                continue

            with open(s1_path, "r", encoding="utf-8") as f:
                sections_y1 = json.load(f)
            with open(s2_path, "r", encoding="utf-8") as f:
                sections_y2 = json.load(f)

            # Compare each section
            for section_key, section_name in _SECTION_FRIENDLY_NAMES.items():
                text_y1 = sections_y1.get(section_key)
                text_y2 = sections_y2.get(section_key)

                # Need both years to have content for this section
                if not text_y1 or not text_y2:
                    continue

                paras_old = _split_paragraphs(text_y1)
                paras_new = _split_paragraphs(text_y2)

                if not paras_old or not paras_new:
                    continue

                change_pct, n_added, n_removed, n_changed = _compute_paragraph_diff(
                    paras_old, paras_new
                )

                # Skip sections with negligible change
                if change_pct < 2.0:
                    continue

                # Build descriptive strings
                added_str = ""
                if n_added > 0:
                    # Try to get topic hints from added paragraphs
                    matcher = difflib.SequenceMatcher(None, paras_old, paras_new)
                    added_topics = []
                    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                        if tag == "insert":
                            for j in range(j1, min(j2, j1 + 2)):
                                added_topics.append(_extract_topic_hint(paras_new[j]))
                    topics_str = "; ".join(added_topics[:3]) if added_topics else "new disclosures"
                    added_str = f"{n_added} new paragraph(s) were added, covering: {topics_str}. "

                removed_str = ""
                if n_removed > 0:
                    matcher = difflib.SequenceMatcher(None, paras_old, paras_new)
                    removed_topics = []
                    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                        if tag == "delete":
                            for i in range(i1, min(i2, i1 + 2)):
                                removed_topics.append(_extract_topic_hint(paras_old[i]))
                    topics_str = "; ".join(removed_topics[:3]) if removed_topics else "prior disclosures"
                    removed_str = f"{n_removed} paragraph(s) were removed, which previously discussed: {topics_str}."

                # Determine change description
                if change_pct > 50:
                    change_desc = "substantially revised"
                    change_verb = "substantially revised"
                elif change_pct > 20:
                    change_desc = "significantly updated"
                    change_verb = "significantly updated"
                elif change_pct > 5:
                    change_desc = "moderately updated"
                    change_verb = "moderately updated"
                else:
                    change_desc = "slightly modified"
                    change_verb = "slightly modified"

                # Generate question
                q_template = rng.choice(_DIFF_QUESTION_TEMPLATES)
                question = q_template.format(
                    company=company_name, section_name=section_name,
                    y1=y1, y2=y2,
                )

                # Generate answer
                a_template = rng.choice(_DIFF_SUMMARY_TEMPLATES)
                answer = a_template.format(
                    company=company_name, section_name=section_name,
                    y1=y1, y2=y2, pct=change_pct,
                    added_str=added_str, removed_str=removed_str,
                    change_desc=change_desc, change_verb=change_verb,
                )
                tuple_obj = normalize_tuple(
                    ticker=ticker,
                    years=[y1, y2],
                    metrics=[section_name.lower()],
                    operation="compare",
                )

                records.append(
                    _build_record(
                        question,
                        answer.strip(),
                        source="diff_summaries",
                        tuple_obj=tuple_obj,
                        extra_metadata={"company": company_name, "section": section_key},
                    )
                )

    rng.shuffle(records)
    # Target 60-80, but take what we get
    if len(records) > 80:
        records = records[:80]

    print(f"Diff Summaries: {len(records)} examples generated")
    output_path = TRAINING_DIR / "diff_summaries.jsonl"
    _save_jsonl(records, output_path)
    return records


# ---------------------------------------------------------------------------
# Combine
# ---------------------------------------------------------------------------

_SOURCE_FILES = {
    "convfinqa": TRAINING_DIR / "convfinqa.jsonl",
    "phrasebank": TRAINING_DIR / "phrasebank.jsonl",
    "xbrl_qa": TRAINING_DIR / "xbrl_qa.jsonl",
    "diff_summaries": TRAINING_DIR / "diff_summaries.jsonl",
}


def combine_all_sources(
    output_path: str = "data/training/finedgar_train.jsonl",
    max_phrasebank_share: float = MAX_PHRASEBANK_SHARE,
    teacher_model: str | None = None,
):
    """Merge sources, enforce split labels, and write benchmark-safe datasets.

    Writes:
    - train set to ``output_path``
    - ``internal_secqa_dev.jsonl``
    - ``heldout_secqa_test.jsonl``
    """
    out = PROJECT_ROOT / output_path
    _ensure_training_dir()

    all_records: list[dict] = []
    source_counts: dict[str, int] = {}

    for source_name, source_path in _SOURCE_FILES.items():
        if not source_path.exists():
            print(f"  [{source_name}] not found at {source_path} — skipping")
            continue
        count = 0
        with open(source_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                all_records.append(json.loads(line))
                count += 1
        source_counts[source_name] = count
        print(f"  [{source_name}] {count} examples")

    if not all_records:
        print("No source files found — nothing to combine.")
        return

    if teacher_model:
        print(f"Annotating narrative/entity records with local teacher: {teacher_model}")
        all_records = annotate_records_with_local_teacher(all_records, teacher_model)

    random.seed(42)
    random.shuffle(all_records)
    phrasebank_records = [
        record for record in all_records
        if (record.get("metadata") or {}).get("source") == "phrasebank"
    ]
    non_phrasebank_records = [
        record for record in all_records
        if (record.get("metadata") or {}).get("source") != "phrasebank"
    ]

    max_phrasebank = int(len(non_phrasebank_records) * max_phrasebank_share)
    if max_phrasebank_share > 0 and phrasebank_records:
        retained_phrasebank = phrasebank_records[:max_phrasebank]
    else:
        retained_phrasebank = []

    filtered_records = non_phrasebank_records + retained_phrasebank
    random.shuffle(filtered_records)

    train_records: list[dict] = []
    internal_dev_records: list[dict] = []
    heldout_test_records: list[dict] = []

    for record in filtered_records:
        role = (record.get("metadata") or {}).get("dataset_role", "train")
        if role == "internal_secqa_dev":
            internal_dev_records.append(record)
        elif role == "heldout_secqa_test":
            heldout_test_records.append(record)
        else:
            train_records.append(record)

    _save_jsonl(train_records, out)
    _save_jsonl(internal_dev_records, TRAINING_DIR / "internal_secqa_dev.jsonl")
    _save_jsonl(heldout_test_records, TRAINING_DIR / "heldout_secqa_test.jsonl")

    summary = {
        "train": len(train_records),
        "internal_secqa_dev": len(internal_dev_records),
        "heldout_secqa_test": len(heldout_test_records),
        "phrasebank_retained": len(retained_phrasebank),
        "phrasebank_original": len(phrasebank_records),
        "max_phrasebank_share": max_phrasebank_share,
    }
    (TRAINING_DIR / "dataset_index.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("\n--- Combined dataset ---")
    for name, count in source_counts.items():
        print(f"  {name}: {count}")
    print(f"  financebench_dev_seen: separate benchmark manifest under data/benchmarks/")
    print(f"  internal_secqa_dev: {len(internal_dev_records)}")
    print(f"  heldout_secqa_test: {len(heldout_test_records)}")
    print(f"  train: {len(train_records)}")


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def validate_dataset(path: str):
    """Validate a training JSONL file.

    Checks:
    1. Every line is valid JSON
    2. Every example has 'messages' with exactly 2 entries
    3. First message role='user', second role='assistant'
    4. No empty content fields
    5. Prints token length distribution (min, max, mean, p95)
    """
    import tiktoken

    filepath = Path(path)
    if not filepath.is_absolute():
        filepath = PROJECT_ROOT / filepath
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    enc = tiktoken.get_encoding("cl100k_base")

    errors: list[str] = []
    token_lengths: list[int] = []

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # 1. Valid JSON
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as e:
                errors.append(f"Line {line_num}: invalid JSON — {e}")
                continue

            # 2. Has 'messages' with exactly 2 entries
            messages = record.get("messages")
            if not isinstance(messages, list) or len(messages) != 2:
                errors.append(
                    f"Line {line_num}: 'messages' must be a list of exactly 2 entries, "
                    f"got {type(messages).__name__} with {len(messages) if isinstance(messages, list) else 'N/A'} entries"
                )
                continue

            # 3. Role checks
            if messages[0].get("role") != "user":
                errors.append(f"Line {line_num}: first message role must be 'user', got '{messages[0].get('role')}'")
            if messages[1].get("role") != "assistant":
                errors.append(f"Line {line_num}: second message role must be 'assistant', got '{messages[1].get('role')}'")

            # 4. No empty content
            for i, msg in enumerate(messages):
                content = msg.get("content", "")
                if not content or not content.strip():
                    errors.append(f"Line {line_num}: message {i} has empty content")

            # Token count for distribution
            full_text = " ".join(msg.get("content", "") for msg in messages)
            token_lengths.append(len(enc.encode(full_text)))

    # Report errors
    if errors:
        print(f"VALIDATION FAILED — {len(errors)} error(s):")
        for err in errors[:20]:
            print(f"  {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
    else:
        print("VALIDATION PASSED — no errors found.")

    # Token distribution
    if token_lengths:
        token_lengths_sorted = sorted(token_lengths)
        n = len(token_lengths_sorted)
        p95_idx = int(n * 0.95)
        p95 = token_lengths_sorted[min(p95_idx, n - 1)]
        print(f"\nToken length distribution ({n} examples):")
        print(f"  Min:  {min(token_lengths)}")
        print(f"  Max:  {max(token_lengths)}")
        print(f"  Mean: {statistics.mean(token_lengths):.1f}")
        print(f"  P95:  {p95}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_SOURCE_PREPARERS = {
    "convfinqa": prepare_convfinqa,
    "phrasebank": prepare_phrasebank,
    "xbrl_qa": prepare_xbrl_qa,
    "diff_summaries": prepare_diff_summaries,
}


def main():
    parser = argparse.ArgumentParser(
        description="Prepare training data for FinEdgar Gemma 4 E4B fine-tuning."
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=None,
        help="Comma-separated list of sources to prepare: convfinqa,phrasebank,xbrl_qa,diff_summaries",
    )
    parser.add_argument(
        "--combine",
        action="store_true",
        help="Combine all available source JSONL files into a single training file.",
    )
    parser.add_argument(
        "--validate",
        type=str,
        default=None,
        help="Path to a JSONL file to validate.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/training/finedgar_train.jsonl",
        help="Output path for --combine (relative to project root).",
    )
    parser.add_argument(
        "--max-phrasebank-share",
        type=float,
        default=MAX_PHRASEBANK_SHARE,
        help="Maximum PhraseBank share to retain in the train split.",
    )
    parser.add_argument(
        "--teacher-model",
        type=str,
        default=None,
        help="Optional local Ollama teacher model for offline metadata annotation, e.g. qwen2.5:7b-instruct.",
    )
    args = parser.parse_args()

    if not any([args.sources, args.combine, args.validate]):
        parser.print_help()
        sys.exit(1)

    # Prepare requested sources
    if args.sources:
        source_names = [s.strip() for s in args.sources.split(",")]
        for name in source_names:
            if name not in _SOURCE_PREPARERS:
                print(f"Unknown source: {name}")
                print(f"Available: {', '.join(_SOURCE_PREPARERS.keys())}")
                sys.exit(1)
            print(f"\n=== Preparing {name} ===")
            _SOURCE_PREPARERS[name]()

    # Combine
    if args.combine:
        print("\n=== Combining all sources ===")
        combine_all_sources(
            output_path=args.output,
            max_phrasebank_share=args.max_phrasebank_share,
            teacher_model=args.teacher_model,
        )

    # Validate
    if args.validate:
        print(f"\n=== Validating {args.validate} ===")
        validate_dataset(args.validate)


if __name__ == "__main__":
    main()
