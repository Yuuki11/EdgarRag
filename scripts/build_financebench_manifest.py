#!/usr/bin/env python3
"""Download the public FinanceBench sample and build a local manifest.

This script is benchmark-safe by design:
- it stores the public evaluation set separately under data/benchmarks/
- it creates an eval-only manifest used for coverage audits and leakage checks
- it does not feed the benchmark into training generation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from datasets import load_dataset

_SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.data.benchmarking import (
    financebench_row_to_manifest_entry,
    load_company_lookup,
)
from backend.data.xbrl_fetcher import METRIC_ALIASES


BENCH_DIR = PROJECT_ROOT / "data" / "benchmarks" / "financebench"
RAW_PATH = BENCH_DIR / "open_source.jsonl"
MANIFEST_PATH = BENCH_DIR / "manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local FinanceBench manifest")
    parser.add_argument(
        "--dataset",
        default="PatronusAI/financebench",
        help="Hugging Face dataset id",
    )
    args = parser.parse_args()

    BENCH_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading FinanceBench dataset: {args.dataset}")
    ds = load_dataset(args.dataset, split="train")
    rows = [dict(row) for row in ds if row.get("dataset_subset_label") == "OPEN_SOURCE"]
    print(f"Loaded {len(rows)} open-source benchmark rows")

    company_to_ticker, _ = load_company_lookup(PROJECT_ROOT / "data" / "companies.json")
    known_metrics = sorted(METRIC_ALIASES.keys())
    manifest = [
        financebench_row_to_manifest_entry(row, company_to_ticker, known_metrics)
        for row in rows
    ]

    with open(RAW_PATH, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "dataset": args.dataset,
                "label": "financebench_dev_seen",
                "questions": manifest,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Wrote raw benchmark rows to {RAW_PATH}")
    print(f"Wrote manifest to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

