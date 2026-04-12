#!/usr/bin/env python3
"""FinanceBench evaluation harness.

Runs the full answer pipeline against all 150 FinanceBench questions and
reports accuracy at three scoring levels: official, internal, and judge.

Usage:
    python scripts/run_financebench_eval.py
    python scripts/run_financebench_eval.py --subset xbrl --scorer official
    python scripts/run_financebench_eval.py --output outputs/eval_runs/v1.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.data.answer_evaluator import (
    ScoreResult,
    compute_retrieval_recall,
    score_internal,
    score_official,
)
from backend.data.answer_pipeline import PipelineResult, answer_question

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────────────────────────


def load_benchmark() -> list[dict]:
    """Load FinanceBench questions with gold answers + routing metadata."""
    manifest_path = PROJECT_ROOT / "data" / "benchmarks" / "financebench" / "manifest.json"
    gold_path = PROJECT_ROOT / "data" / "benchmarks" / "financebench" / "open_source.jsonl"

    # Load manifest (has routing info: ticker, route_type, years)
    with open(manifest_path) as f:
        manifest_data = json.load(f)
    manifest_questions = {q["financebench_id"]: q for q in manifest_data["questions"]}

    # Load gold answers
    gold_records = {}
    with open(gold_path) as f:
        for line in f:
            record = json.loads(line)
            gold_records[record["financebench_id"]] = record

    # Merge: manifest routing + gold answers/evidence
    benchmark = []
    for fid, manifest_q in manifest_questions.items():
        gold = gold_records.get(fid)
        if not gold:
            logger.warning("No gold answer for %s", fid)
            continue
        benchmark.append({
            "financebench_id": fid,
            "question": gold["question"],
            "gold_answer": gold["answer"],
            "gold_evidence": [e.get("evidence_text", "") for e in gold.get("evidence", [])],
            "justification": gold.get("justification", ""),
            "company": gold.get("company", manifest_q.get("company", "")),
            "ticker": manifest_q.get("ticker", ""),
            "doc_period": manifest_q.get("doc_period") or gold.get("doc_period"),
            "question_type": gold.get("question_type", ""),
            "question_reasoning": gold.get("question_reasoning", ""),
            "doc_type": gold.get("doc_type", ""),
            "route_type": manifest_q.get("route_type", "rag"),
            "operation": manifest_q.get("normalized_tuple", {}).get("operation", ""),
        })

    return benchmark


# ──────────────────────────────────────────────────────────────────────────────
# Evaluation loop
# ──────────────────────────────────────────────────────────────────────────────


def run_eval(
    benchmark: list[dict],
    subset: str | None = None,
    scorer: str = "official",
) -> dict:
    """Run evaluation on benchmark questions.

    Args:
        benchmark: List of question dicts
        subset: Filter by route_type ("xbrl", "rag") or None for all
        scorer: Which scorer to use as primary ("official", "internal")

    Returns:
        Results dict with per-question details and aggregates
    """
    if subset:
        benchmark = [q for q in benchmark if q["route_type"] == subset]
        logger.info("Filtered to %d questions for route: %s", len(benchmark), subset)

    results = []
    total = len(benchmark)
    official_correct = 0
    internal_correct = 0
    retrieval_recalls = []

    logger.info("Starting evaluation on %d questions...", total)
    eval_start = time.time()

    for i, q in enumerate(benchmark, 1):
        fid = q["financebench_id"]
        question = q["question"]
        ticker = q["ticker"]
        years = [q["doc_period"]] if q["doc_period"] else []

        logger.info("[%d/%d] %s — %s", i, total, fid, question[:60])

        # Run pipeline
        pipeline_result = answer_question(
            question=question,
            ticker=ticker,
            years=years,
        )

        # Score
        predicted = pipeline_result.answer
        gold = q["gold_answer"]

        official_score = score_official(predicted, gold)
        internal_score = score_internal(predicted, gold)

        if official_score.correct:
            official_correct += 1
        if internal_score.correct:
            internal_correct += 1

        # Retrieval recall
        retrieved_texts = [p.get("text", "") for p in pipeline_result.retrieved_passages]
        recall = compute_retrieval_recall(retrieved_texts, q["gold_evidence"])
        if recall["recall_at_5"] is not None:
            retrieval_recalls.append(recall["recall_at_5"])

        # Log result
        status = "CORRECT" if official_score.correct else ("~CLOSE" if internal_score.correct else "WRONG")
        logger.info(
            "  %s | predicted: %s | gold: %s | route: %s | latency: %.0fms",
            status,
            predicted[:50] if predicted else "<empty>",
            gold[:50],
            pipeline_result.route,
            pipeline_result.latency_ms,
        )

        results.append({
            "financebench_id": fid,
            "question": question,
            "ticker": ticker,
            "years": years,
            "doc_type": q.get("doc_type", ""),
            "route_type": q["route_type"],
            "actual_route": pipeline_result.route,
            "operation": pipeline_result.operation,
            "metrics": pipeline_result.metrics,
            "question_plan": pipeline_result.question_plan,
            "predicted": predicted,
            "gold": gold,
            "official_correct": official_score.correct,
            "internal_correct": internal_score.correct,
            "official_match_type": official_score.match_type,
            "retrieval_recall_at_5": recall["recall_at_5"],
            "latency_ms": pipeline_result.latency_ms,
            "fallback_used": pipeline_result.fallback_used,
            "error": pipeline_result.error,
        })

    elapsed = time.time() - eval_start

    # Aggregate metrics
    route_breakdown = {}
    doc_type_breakdown = {}
    answer_mode_breakdown = {}
    for r in results:
        rt = r["route_type"]
        if rt not in route_breakdown:
            route_breakdown[rt] = {"total": 0, "official_correct": 0, "internal_correct": 0}
        route_breakdown[rt]["total"] += 1
        if r["official_correct"]:
            route_breakdown[rt]["official_correct"] += 1
        if r["internal_correct"]:
            route_breakdown[rt]["internal_correct"] += 1

        doc_type = r.get("doc_type") or "unknown"
        if doc_type not in doc_type_breakdown:
            doc_type_breakdown[doc_type] = {"total": 0, "official_correct": 0}
        doc_type_breakdown[doc_type]["total"] += 1
        if r["official_correct"]:
            doc_type_breakdown[doc_type]["official_correct"] += 1

        answer_mode = (r.get("question_plan") or {}).get("answer_mode", "unknown")
        if answer_mode not in answer_mode_breakdown:
            answer_mode_breakdown[answer_mode] = {"total": 0, "official_correct": 0}
        answer_mode_breakdown[answer_mode]["total"] += 1
        if r["official_correct"]:
            answer_mode_breakdown[answer_mode]["official_correct"] += 1

    for rt, stats in route_breakdown.items():
        stats["official_accuracy"] = stats["official_correct"] / max(stats["total"], 1)
        stats["internal_accuracy"] = stats["internal_correct"] / max(stats["total"], 1)
    for bucket in (doc_type_breakdown, answer_mode_breakdown):
        for _, stats in bucket.items():
            stats["official_accuracy"] = stats["official_correct"] / max(stats["total"], 1)

    avg_recall = sum(retrieval_recalls) / max(len(retrieval_recalls), 1)
    avg_latency = sum(r["latency_ms"] for r in results) / max(len(results), 1)

    summary = {
        "total_questions": total,
        "official_correct": official_correct,
        "official_accuracy": official_correct / max(total, 1),
        "internal_correct": internal_correct,
        "internal_accuracy": internal_correct / max(total, 1),
        "avg_retrieval_recall_at_5": avg_recall,
        "avg_latency_ms": avg_latency,
        "total_elapsed_s": elapsed,
        "route_breakdown": route_breakdown,
        "doc_type_breakdown": doc_type_breakdown,
        "answer_mode_breakdown": answer_mode_breakdown,
        "subset_filter": subset,
        "scorer": scorer,
    }

    return {"summary": summary, "results": results}


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Run FinanceBench evaluation")
    parser.add_argument("--subset", choices=["xbrl", "rag", "hybrid"], help="Filter by route type")
    parser.add_argument("--scorer", choices=["official", "internal"], default="official", help="Primary scorer")
    parser.add_argument("--output", type=str, help="Output path for results JSON")
    parser.add_argument("--limit", type=int, help="Limit to first N questions (for testing)")
    args = parser.parse_args()

    # Load benchmark
    benchmark = load_benchmark()
    logger.info("Loaded %d FinanceBench questions", len(benchmark))

    if args.limit:
        benchmark = benchmark[: args.limit]
        logger.info("Limited to first %d questions", args.limit)

    # Run eval
    eval_results = run_eval(benchmark, subset=args.subset, scorer=args.scorer)

    # Print summary
    s = eval_results["summary"]
    print("\n" + "=" * 60)
    print("FINANCEBENCH EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Total questions:        {s['total_questions']}")
    print(f"  Official accuracy:      {s['official_correct']}/{s['total_questions']} ({s['official_accuracy']:.1%})")
    print(f"  Internal accuracy:      {s['internal_correct']}/{s['total_questions']} ({s['internal_accuracy']:.1%})")
    print(f"  Avg retrieval recall@5: {s['avg_retrieval_recall_at_5']:.3f}")
    print(f"  Avg latency:            {s['avg_latency_ms']:.0f}ms")
    print(f"  Total elapsed:          {s['total_elapsed_s']:.1f}s")
    print()
    print("  Route breakdown:")
    for rt, stats in s["route_breakdown"].items():
        print(
            f"    {rt:8s}: {stats['official_correct']}/{stats['total']} "
            f"({stats['official_accuracy']:.1%} official, {stats['internal_accuracy']:.1%} internal)"
        )
    print("=" * 60)

    # Save results
    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = PROJECT_ROOT / "outputs" / "eval_runs"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"eval_{timestamp}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(eval_results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
