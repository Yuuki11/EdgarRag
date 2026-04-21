#!/usr/bin/env python3
"""Audit local SEC artifact coverage against the FinanceBench manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _status_for_year(ticker: str, year: int) -> dict[str, bool]:
    filings_dir = PROJECT_ROOT / "data" / "filings" / ticker / str(year)
    parsed_dir = PROJECT_ROOT / "data" / "parsed" / ticker / str(year)
    chunks_dir = PROJECT_ROOT / "data" / "chunks" / ticker / str(year)

    filings_ready = (filings_dir / "10-K.htm").exists() or any(path.is_file() for path in filings_dir.rglob("*"))
    parsed_ready = (parsed_dir / "sections.json").exists() or any(path.is_file() for path in parsed_dir.rglob("*.json"))
    chunks_ready = (chunks_dir / "chunks.json").exists() or any(path.name == "chunks.json" for path in chunks_dir.rglob("chunks.json"))

    return {
        "xbrl_ready": (PROJECT_ROOT / "data" / "xbrl_cache" / f"{ticker}.json").exists(),
        "filings_ready": filings_ready,
        "parsed_ready": parsed_ready,
        "chunks_ready": chunks_ready,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit FinanceBench coverage")
    parser.add_argument(
        "--manifest",
        default="data/benchmarks/financebench/manifest.json",
        help="FinanceBench manifest path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable report",
    )
    args = parser.parse_args()

    manifest_path = PROJECT_ROOT / args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    questions = manifest["questions"]

    required: dict[str, set[int]] = {}
    for question in questions:
        ticker = question["ticker"]
        years = question["normalized_tuple"]["years"] or [question.get("doc_period")]
        required.setdefault(ticker, set()).update(int(year) for year in years if year)

    report = []
    for ticker in sorted(required):
        for year in sorted(required[ticker]):
            status = _status_for_year(ticker, year)
            report.append(
                {
                    "ticker": ticker,
                    "year": year,
                    **status,
                    "complete": all(status.values()),
                }
            )

    if args.json:
        print(json.dumps(report, indent=2))
        return

    complete = sum(1 for item in report if item["complete"])
    print("Coverage audit against financebench_dev_seen")
    print(f"Complete company-year pairs: {complete}/{len(report)}")
    for item in report:
        flags = ", ".join(
            f"{key}={'yes' if item[key] else 'no'}"
            for key in ("xbrl_ready", "filings_ready", "parsed_ready", "chunks_ready")
        )
        print(f"  {item['ticker']} FY{item['year']}: {flags}")


if __name__ == "__main__":
    main()
