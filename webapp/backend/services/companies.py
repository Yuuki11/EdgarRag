"""Load the company/year catalog exposed to the frontend."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..schemas import CompanyYears

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPANIES_JSON = REPO_ROOT / "data" / "companies.json"
CHUNKS_DIR = REPO_ROOT / "data" / "chunks"


@lru_cache(maxsize=1)
def load_companies() -> list[CompanyYears]:
    raw = json.loads(COMPANIES_JSON.read_text())
    out: list[CompanyYears] = []
    for entry in raw:
        ticker = entry["ticker"]
        years = _years_for(ticker)
        out.append(
            CompanyYears(
                ticker=ticker,
                name=entry.get("name", ticker),
                sector=entry.get("sector", "Unknown"),
                years=years,
            )
        )
    out.sort(key=lambda c: c.ticker)
    return out


def _years_for(ticker: str) -> list[int]:
    company_dir = CHUNKS_DIR / ticker
    if not company_dir.is_dir():
        return []
    years: list[int] = []
    for child in company_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            years.append(int(child.name))
        except ValueError:
            continue
    return sorted(years)
