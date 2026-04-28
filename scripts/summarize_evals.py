#!/usr/bin/env python3
"""Summarise every eval JSON in outputs/eval_runs/.

Writes outputs/eval_runs/results.csv and prints a markdown table to stdout
suitable for pasting into README.md.

Usage:
    python scripts/summarize_evals.py
    python scripts/summarize_evals.py --csv outputs/eval_runs/results.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "outputs" / "eval_runs"


def _pct(x):
    return "" if x is None else f"{x * 100:.1f}%"


def _date_from_name(name: str) -> str:
    m = re.search(r"(\d{8})", name)
    if not m:
        return ""
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def summarise_one(path: Path) -> dict:
    data = json.loads(path.read_text())
    s = data.get("summary", data)
    rb = s.get("route_breakdown") or {}
    xbrl = rb.get("xbrl") or {}
    rag = rb.get("rag") or {}
    return {
        "file": path.name,
        "date": _date_from_name(path.name),
        "total_questions": s.get("total_questions"),
        "official_accuracy": s.get("official_accuracy"),
        "internal_accuracy": s.get("internal_accuracy"),
        "xbrl_total": xbrl.get("total"),
        "xbrl_accuracy": xbrl.get("official_accuracy"),
        "rag_total": rag.get("total"),
        "rag_accuracy": rag.get("official_accuracy"),
        "avg_recall_at_5": s.get("avg_retrieval_recall_at_5"),
        "avg_latency_ms": s.get("avg_latency_ms"),
    }


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def print_markdown(rows: list[dict]) -> None:
    print("| # | Date | Run | Overall Acc | XBRL Acc | RAG Acc | Recall@5 | Avg Latency |")
    print("|---|------|-----|------------:|---------:|--------:|---------:|------------:|")
    for i, r in enumerate(rows, 1):
        print(
            f"| {i} | {r['date'] or '—'} | `{r['file']}` "
            f"| {_pct(r['official_accuracy'])} "
            f"| {_pct(r['xbrl_accuracy'])} (n={r['xbrl_total'] or 0}) "
            f"| {_pct(r['rag_accuracy'])} (n={r['rag_total'] or 0}) "
            f"| {_pct(r['avg_recall_at_5'])} "
            f"| {r['avg_latency_ms']:.0f} ms |"
            if r["avg_latency_ms"] is not None
            else ""
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    ap.add_argument("--csv", type=Path, default=EVAL_DIR / "results.csv")
    args = ap.parse_args()

    paths = sorted(args.eval_dir.glob("eval_*.json"))
    if not paths:
        raise SystemExit(f"No eval_*.json found in {args.eval_dir}")

    rows = [summarise_one(p) for p in paths]
    write_csv(rows, args.csv)
    print(f"Wrote {args.csv} ({len(rows)} runs)\n")
    print_markdown(rows)


if __name__ == "__main__":
    main()
