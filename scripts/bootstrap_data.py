#!/usr/bin/env python3
"""
Bootstrap script: downloads filings and XBRL data for supported companies.

This is corpus-building infrastructure only. It broadens retrieval coverage by
ingesting annual and selected current-report filings without using benchmark
question/answer pairs as training supervision.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.data.chunker import chunk_section
from backend.data.filing_downloader import (
    download_filing,
    download_filings,
    find_10k_filing,
)
from backend.data.models import SECTION_NAMES, Section
from backend.data.section_parser import parse_10k_sections
from backend.data.ticker_resolver import resolve_ticker
from backend.data.xbrl_fetcher import fetch_company_facts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COMPANIES_JSON = _PROJECT_ROOT / "data" / "companies.json"
PARSED_DIR = _PROJECT_ROOT / "data" / "parsed"
CHUNKS_DIR = _PROJECT_ROOT / "data" / "chunks"
TARGET_YEARS = list(range(2019, 2024))
DEFAULT_FORMS = ("10-K", "10-Q", "8-K")


def load_companies(limit: int | None = None) -> list[dict]:
    with open(COMPANIES_JSON, "r", encoding="utf-8") as fh:
        companies = json.load(fh)
    if limit is not None:
        companies = companies[:limit]
    return companies


def load_required_years_from_manifest(manifest_path: Path) -> dict[str, list[int]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    questions = data.get("questions", []) if isinstance(data, dict) else data
    required: dict[str, set[int]] = {}
    for question in questions:
        ticker = question["ticker"].upper()
        years = question.get("normalized_tuple", {}).get("years") or []
        required.setdefault(ticker, set()).update(int(year) for year in years if year)
    return {ticker: sorted(years) for ticker, years in required.items()}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _process_10k_filing(ticker: str, year: int) -> None:
    ticker_upper = ticker.upper()
    filing_meta = find_10k_filing(ticker, year)
    if not filing_meta:
        logger.info("  No 10-K found for %s FY%d (skipping)", ticker_upper, year)
        return

    try:
        filepath = download_filing(ticker, year, filing_meta)
        logger.info("  10-K %s FY%d -> %s", ticker_upper, year, filepath)
    except Exception as exc:
        logger.error("  Error downloading 10-K %s FY%d: %s", ticker_upper, year, exc)
        return

    try:
        sections = parse_10k_sections(filepath)
    except Exception as exc:
        logger.error("  Error parsing 10-K %s FY%d: %s", ticker_upper, year, exc)
        return

    parsed_dir = PARSED_DIR / ticker_upper / str(year)
    _write_json(parsed_dir / "sections.json", sections)
    found = sum(1 for value in sections.values() if value is not None)
    logger.info("  Parsed %d/5 sections for %s FY%d", found, ticker_upper, year)

    filing_date = filing_meta["filing_date"] if filing_meta else ""
    source_url = filing_meta["url"] if filing_meta else ""
    document_id = filing_meta["document_id"] if filing_meta else f"10-K_{year}"

    all_chunks: list[dict] = []
    for section_enum in Section:
        section_key = section_enum.value
        section_text = sections.get(section_key)
        if section_text is None:
            continue
        section_name = SECTION_NAMES.get(section_enum, section_key)
        chunks = chunk_section(
            text=section_text,
            ticker=ticker_upper,
            year=year,
            document_id=document_id,
            section=section_key,
            section_name=section_name,
            filing_date=filing_date,
            source_url=source_url,
            form_type="10-K",
        )
        all_chunks.extend(asdict(chunk) for chunk in chunks)

    if all_chunks:
        _write_json(CHUNKS_DIR / ticker_upper / str(year) / "chunks.json", all_chunks)
        logger.info("  Saved %d chunks for %s FY%d", len(all_chunks), ticker_upper, year)


def _process_generic_filings(
    ticker: str,
    year: int,
    forms: tuple[str, ...],
    limit_per_form: int | None = None,
) -> None:
    from backend.data.document_parser import parse_generic_document

    ticker_upper = ticker.upper()
    try:
        filings = download_filings(
            ticker,
            year,
            forms=forms,
            limit_per_form=limit_per_form,
        )
    except Exception as exc:
        logger.error("  Error downloading generic filings for %s FY%d: %s", ticker_upper, year, exc)
        return

    if not filings:
        logger.info("  No %s filings found for %s FY%d", ",".join(forms), ticker_upper, year)
        return

    for filing in filings:
        form_type = filing["form"]
        document_id = filing["document_id"]
        local_path = filing["local_path"]
        try:
            parsed = parse_generic_document(local_path)
        except Exception as exc:
            logger.error("  Error parsing %s %s FY%d: %s", form_type, ticker_upper, year, exc)
            continue

        text = parsed.get("full_document")
        if not text:
            logger.info("  Empty extracted text for %s %s FY%d", form_type, ticker_upper, year)
            continue

        _write_json(
            PARSED_DIR / ticker_upper / str(year) / document_id / "document.json",
            {
                "document_id": document_id,
                "form_type": form_type,
                "filing_date": filing.get("filing_date", ""),
                "report_date": filing.get("report_date", ""),
                "source_url": filing.get("url", ""),
                "text": text,
            },
        )

        section_key = f"form_{form_type.lower().replace('-', '').replace('/', '')}"
        section_name = f"{form_type} Document"
        chunks = chunk_section(
            text=text,
            ticker=ticker_upper,
            year=year,
            document_id=document_id,
            section=section_key,
            section_name=section_name,
            filing_date=filing.get("filing_date", ""),
            source_url=filing.get("url", ""),
            form_type=form_type,
        )
        if not chunks:
            logger.info("  No chunks produced for %s %s FY%d", form_type, ticker_upper, year)
            continue

        _write_json(
            CHUNKS_DIR / ticker_upper / str(year) / document_id / "chunks.json",
            [asdict(chunk) for chunk in chunks],
        )
        logger.info("  Saved %d chunks for %s %s FY%d", len(chunks), form_type, ticker_upper, year)


def process_company(
    ticker: str,
    name: str,
    index: int,
    total: int,
    target_years: list[int],
    forms: tuple[str, ...],
    limit_per_form: int | None = None,
) -> None:
    print(f"[{index}/{total}] Processing {ticker} ({name}) for years {target_years} and forms {forms}...")

    try:
        cik, sec_name = resolve_ticker(ticker)
        logger.info("  Resolved %s -> CIK %s (%s)", ticker, cik, sec_name)
    except Exception as exc:
        logger.error("  Failed to resolve ticker %s: %s", ticker, exc)
        return

    try:
        fetch_company_facts(ticker)
        logger.info("  Fetched XBRL facts for %s", ticker)
    except Exception as exc:
        logger.warning("  Could not fetch XBRL facts for %s: %s", ticker, exc)

    for year in target_years:
        if "10-K" in forms:
            _process_10k_filing(ticker, year)
        generic_forms = tuple(form for form in forms if form != "10-K")
        if generic_forms:
            _process_generic_filings(ticker, year, generic_forms, limit_per_form=limit_per_form)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap SEC filing data for all supported companies.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N companies.")
    parser.add_argument("--years", type=str, default=None, help="Comma-separated fiscal years to process.")
    parser.add_argument(
        "--benchmark-manifest",
        type=str,
        default=None,
        help="Optional manifest used only to limit company/year coverage.",
    )
    parser.add_argument(
        "--forms",
        type=str,
        default=",".join(DEFAULT_FORMS),
        help="Comma-separated forms to ingest, e.g. 10-K,10-Q,8-K",
    )
    parser.add_argument(
        "--limit-per-form",
        type=int,
        default=None,
        help="Optional maximum documents to ingest per form type and year.",
    )
    args = parser.parse_args()

    companies = load_companies(limit=args.limit)
    total = len(companies)
    if args.years:
        default_years = sorted({int(part.strip()) for part in args.years.split(",") if part.strip()})
    else:
        default_years = TARGET_YEARS

    manifest_years: dict[str, list[int]] = {}
    if args.benchmark_manifest:
        manifest_years = load_required_years_from_manifest(Path(args.benchmark_manifest))

    forms = tuple(part.strip().upper() for part in args.forms.split(",") if part.strip())

    print(f"Processing {total} companies, default years {default_years}, forms {forms}")
    print("=" * 60)

    failed: list[str] = []
    for i, company in enumerate(companies, start=1):
        ticker = company["ticker"]
        name = company["name"]
        if manifest_years and ticker not in manifest_years:
            logger.info("Skipping %s because it is not required by the manifest", ticker)
            continue
        target_years = manifest_years.get(ticker, default_years)
        try:
            process_company(
                ticker,
                name,
                i,
                total,
                target_years,
                forms,
                limit_per_form=args.limit_per_form,
            )
        except Exception as exc:
            logger.error("FATAL error processing %s: %s", ticker, exc, exc_info=True)
            failed.append(ticker)
        time.sleep(0.2)

    print("=" * 60)
    print(f"Done. {total - len(failed)}/{total} companies processed successfully.")
    if failed:
        print(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
