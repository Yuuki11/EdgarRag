"""Three-tier answer evaluation for FinanceBench.

Scoring modes:
1. official  — strict match (primary metric, mirrors FinanceBench eval)
2. internal  — fuzzy numeric normalization (diagnostic, identifies "almost right")
3. judge     — LLM semantic equivalence (error analysis only, never optimize against)
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field


# ──────────────────────────────────────────────────────────────────────────────
# Numeric parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

_MULTIPLIERS = {
    "trillion": 1e12,
    "billion": 1e9,
    "million": 1e6,
    "thousand": 1e3,
    "mn": 1e6,
    "bn": 1e9,
    "tn": 1e12,
}

_CURRENCY_RE = re.compile(r"[\$€£¥]")
_PARENS_NEG_RE = re.compile(r"\([\$€£¥]?\s*([0-9,.\s]+)\)")


def _strip_formatting(s: str) -> str:
    """Remove currency symbols, commas, whitespace from a numeric string."""
    s = _CURRENCY_RE.sub("", s)
    s = s.replace(",", "").replace(" ", "").strip()
    return s


def parse_numeric(text: str) -> float | None:
    """Extract a numeric value from text, handling financial formatting.

    Handles: $1,577.00, ($370), 28.5%, 1.2 billion, -5.3%, ~$8.70
    Returns None if no numeric value can be extracted.
    """
    if not text:
        return None

    text = text.strip()

    # Handle percentage
    is_pct = "%" in text or "percent" in text.lower()
    text_clean = text.replace("%", "").replace("percent", "").strip()

    # Handle parenthetical negatives: ($370) or (370)
    paren_match = _PARENS_NEG_RE.search(text_clean)
    if paren_match:
        text_clean = "-" + _strip_formatting(paren_match.group(1))
    else:
        text_clean = _strip_formatting(text_clean)

    # Remove leading ~ or approximately
    text_clean = re.sub(r"^[~≈]", "", text_clean)

    # Check for multiplier words
    multiplier = 1.0
    text_lower = text.lower()
    for word, mult in _MULTIPLIERS.items():
        if re.search(rf"\b{re.escape(word)}s?\b", text_lower):
            multiplier = mult
            text_clean = re.sub(rf"(?i)\b{re.escape(word)}s?\b", "", text_clean)
            break

    # Extract the numeric part
    num_match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", text_clean)
    if not num_match:
        return None

    value = float(num_match.group()) * multiplier

    # If it was a percentage, keep as-is (28.5% → 28.5)
    # Don't convert to decimal form
    return value


def parse_yes_no(text: str) -> bool | None:
    """Extract yes/no answer from text."""
    text_lower = text.strip().lower()
    if text_lower.startswith("yes"):
        return True
    if text_lower.startswith("no"):
        return False
    if "yes" in text_lower and "no" not in text_lower:
        return True
    if "no" in text_lower and "yes" not in text_lower:
        return False
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Scoring functions
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ScoreResult:
    """Result of scoring a predicted answer against gold."""

    correct: bool
    scorer: str  # "official", "internal", "judge"
    match_type: str = ""  # "exact", "numeric", "yes_no", "semantic"
    predicted_parsed: str = ""
    gold_parsed: str = ""
    details: dict = field(default_factory=dict)


def score_official(predicted: str, gold: str) -> ScoreResult:
    """Strict scoring matching FinanceBench evaluation protocol.

    - Exact string containment (gold in predicted or predicted in gold)
    - For numeric answers: parsed values must match within ±$0.01 or ±0.1%
    - For yes/no: binary match
    """
    if not predicted or not gold:
        return ScoreResult(correct=False, scorer="official", match_type="empty")

    predicted = predicted.strip()
    gold = gold.strip()

    # Exact containment (case-insensitive)
    if gold.lower() in predicted.lower() or predicted.lower() in gold.lower():
        return ScoreResult(
            correct=True,
            scorer="official",
            match_type="exact",
            predicted_parsed=predicted,
            gold_parsed=gold,
        )

    # Yes/no questions
    pred_yn = parse_yes_no(predicted)
    gold_yn = parse_yes_no(gold)
    if pred_yn is not None and gold_yn is not None:
        return ScoreResult(
            correct=pred_yn == gold_yn,
            scorer="official",
            match_type="yes_no",
            predicted_parsed=str(pred_yn),
            gold_parsed=str(gold_yn),
        )

    # Numeric comparison
    pred_num = parse_numeric(predicted)
    gold_num = parse_numeric(gold)
    if pred_num is not None and gold_num is not None:
        # Check if percentage context
        is_pct = "%" in gold or "percent" in gold.lower()

        if is_pct:
            # For percentages: allow ±0.1 absolute
            correct = abs(pred_num - gold_num) <= 0.1
        elif abs(gold_num) < 1.0:
            # Small numbers: absolute tolerance
            correct = abs(pred_num - gold_num) <= 0.01
        else:
            # Large numbers: relative tolerance ±0.5%
            correct = abs(pred_num - gold_num) / abs(gold_num) <= 0.005

        return ScoreResult(
            correct=correct,
            scorer="official",
            match_type="numeric",
            predicted_parsed=str(pred_num),
            gold_parsed=str(gold_num),
            details={"is_pct": is_pct},
        )

    return ScoreResult(
        correct=False,
        scorer="official",
        match_type="no_match",
        predicted_parsed=predicted[:100],
        gold_parsed=gold[:100],
    )


def score_internal(predicted: str, gold: str) -> ScoreResult:
    """Fuzzy scoring for diagnostics — identifies "almost right" answers.

    More lenient than official:
    - Numeric: ±1% relative tolerance
    - Handles unit mismatches (millions vs raw number)
    - Handles formatting differences
    """
    if not predicted or not gold:
        return ScoreResult(correct=False, scorer="internal", match_type="empty")

    predicted = predicted.strip()
    gold = gold.strip()

    # Exact containment
    if gold.lower() in predicted.lower() or predicted.lower() in gold.lower():
        return ScoreResult(
            correct=True,
            scorer="internal",
            match_type="exact",
            predicted_parsed=predicted,
            gold_parsed=gold,
        )

    # Yes/no
    pred_yn = parse_yes_no(predicted)
    gold_yn = parse_yes_no(gold)
    if pred_yn is not None and gold_yn is not None:
        return ScoreResult(
            correct=pred_yn == gold_yn,
            scorer="internal",
            match_type="yes_no",
            predicted_parsed=str(pred_yn),
            gold_parsed=str(gold_yn),
        )

    # Numeric with lenient tolerance
    pred_num = parse_numeric(predicted)
    gold_num = parse_numeric(gold)
    if pred_num is not None and gold_num is not None:
        if gold_num == 0:
            correct = abs(pred_num) < 0.01
        else:
            rel_error = abs(pred_num - gold_num) / abs(gold_num)
            correct = rel_error <= 0.01  # 1% tolerance

            # Also try unit mismatch: maybe one is in millions, other raw
            if not correct:
                for factor in [1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9]:
                    adj = pred_num * factor
                    if abs(adj - gold_num) / abs(gold_num) <= 0.01:
                        correct = True
                        break

        return ScoreResult(
            correct=correct,
            scorer="internal",
            match_type="numeric",
            predicted_parsed=str(pred_num),
            gold_parsed=str(gold_num),
            details={"rel_error": abs(pred_num - gold_num) / max(abs(gold_num), 1e-10)},
        )

    return ScoreResult(
        correct=False,
        scorer="internal",
        match_type="no_match",
        predicted_parsed=predicted[:100],
        gold_parsed=gold[:100],
    )


def compute_retrieval_recall(
    retrieved_passages: list[str], gold_evidence: list[str], threshold: float = 0.3
) -> dict:
    """Measure how well retrieved passages cover the gold evidence.

    Uses token overlap between retrieved passages and gold evidence text.
    Returns recall metrics at various k values.
    """
    if not gold_evidence:
        return {"recall_at_5": None, "recall_at_10": None, "evidence_found": False}

    # Tokenize gold evidence
    gold_tokens = set()
    for ev in gold_evidence:
        gold_tokens.update(re.findall(r"[A-Za-z0-9]+", ev.lower()))

    # Remove stopwords (minimal set)
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "to", "for", "and", "or", "on", "at", "by"}
    gold_tokens -= stopwords

    if not gold_tokens:
        return {"recall_at_5": None, "recall_at_10": None, "evidence_found": False}

    def _coverage_at_k(k: int) -> float:
        """Fraction of gold tokens found in top-k passages."""
        retrieved_tokens = set()
        for passage in retrieved_passages[:k]:
            retrieved_tokens.update(re.findall(r"[A-Za-z0-9]+", passage.lower()))
        retrieved_tokens -= stopwords
        overlap = gold_tokens & retrieved_tokens
        return len(overlap) / len(gold_tokens)

    recall_5 = _coverage_at_k(5)
    recall_10 = _coverage_at_k(10)

    return {
        "recall_at_5": recall_5,
        "recall_at_10": recall_10,
        "evidence_found": recall_5 >= threshold,
    }
