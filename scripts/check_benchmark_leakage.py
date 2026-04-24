#!/usr/bin/env python3
"""Fail if generated training data overlaps with eval-only FinanceBench tuples."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.data.benchmarking import manifest_tuple_keys, record_tuple_key


def iter_records(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check benchmark tuple leakage")
    parser.add_argument(
        "paths",
        nargs="+",
        help="Training JSONL files to inspect",
    )
    parser.add_argument(
        "--manifest",
        default="data/benchmarks/financebench/manifest.json",
        help="FinanceBench manifest path",
    )
    args = parser.parse_args()

    eval_keys = manifest_tuple_keys(PROJECT_ROOT / args.manifest)
    if not eval_keys:
        print(f"No eval-only tuple keys found in {args.manifest}")
        sys.exit(1)

    overlaps: list[tuple[str, str]] = []
    for raw_path in args.paths:
        path = PROJECT_ROOT / raw_path if not Path(raw_path).is_absolute() else Path(raw_path)
        for record in iter_records(path):
            tuple_key = record_tuple_key(record)
            if tuple_key and tuple_key in eval_keys:
                overlaps.append((str(path), tuple_key))

    if overlaps:
        print("BENCHMARK LEAKAGE DETECTED")
        for path, tuple_key in overlaps[:20]:
            print(f"  {path}: {tuple_key}")
        if len(overlaps) > 20:
            print(f"  ... and {len(overlaps) - 20} more")
        sys.exit(1)

    print("No FinanceBench tuple leakage detected.")


if __name__ == "__main__":
    main()

