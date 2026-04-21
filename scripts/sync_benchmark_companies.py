#!/usr/bin/env python3
"""Sync missing benchmark companies into data/companies.json.

This script uses the local FinanceBench manifest plus SEC ticker metadata to:
- append missing, resolvable companies to data/companies.json
- preserve existing entries
- report unresolved companies that likely require manual CIK support
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.data.benchmarking import load_company_lookup, resolve_company_ticker


def load_manifest_questions(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) else data


def load_sec_lookup() -> dict[str, str]:
    raw = json.loads((PROJECT_ROOT / "data" / "company_tickers.json").read_text(encoding="utf-8"))
    return {
        str(entry["ticker"]).upper(): str(entry["title"]).strip()
        for entry in raw.values()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync FinanceBench companies into companies.json")
    parser.add_argument(
        "--manifest",
        default="data/benchmarks/financebench/manifest.json",
        help="Benchmark manifest path",
    )
    parser.add_argument(
        "--companies",
        default="data/companies.json",
        help="Target companies.json path",
    )
    args = parser.parse_args()

    manifest_path = PROJECT_ROOT / args.manifest
    companies_path = PROJECT_ROOT / args.companies

    questions = load_manifest_questions(manifest_path)
    companies = json.loads(companies_path.read_text(encoding="utf-8"))
    existing = {entry["ticker"].upper() for entry in companies}
    company_to_ticker, ticker_to_company = load_company_lookup(companies_path)
    sec_lookup = load_sec_lookup()

    by_company: dict[str, dict] = {}
    for question in questions:
        company = question["company"].strip()
        item = by_company.setdefault(
            company,
            {
                "company": company,
                "gics_sector": None,
                "doc_names": set(),
            },
        )
        item["gics_sector"] = item["gics_sector"] or question.get("gics_sector")
        if question.get("doc_name"):
            item["doc_names"].add(question["doc_name"])

    additions: list[dict] = []
    unresolved: list[dict] = []

    for company, info in sorted(by_company.items()):
        resolved = resolve_company_ticker(company, company_to_ticker)
        if resolved is None:
            unresolved.append(
                {
                    "company": company,
                    "doc_names": sorted(info["doc_names"]),
                }
            )
            continue
        if resolved in existing:
            continue

        additions.append(
            {
                "ticker": resolved,
                "name": sec_lookup.get(resolved, ticker_to_company.get(resolved, company)),
                "sector": info["gics_sector"] or "Unknown",
            }
        )
        existing.add(resolved)

    if additions:
        companies.extend(sorted(additions, key=lambda item: item["ticker"]))
        companies_path.write_text(
            json.dumps(sorted(companies, key=lambda item: item["ticker"]), indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Added {len(additions)} companies to {companies_path}")
    for item in additions:
        print(f"  {item['ticker']}: {item['name']} [{item['sector']}]")

    print(f"\nUnresolved companies: {len(unresolved)}")
    for item in unresolved:
        print(f"  {item['company']} :: {', '.join(item['doc_names'][:3])}")


if __name__ == "__main__":
    main()

