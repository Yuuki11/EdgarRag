"""XBRL Company Facts fetcher for SEC EDGAR.

Fetches structured financial data from SEC's XBRL API, with caching,
rate limiting, metric alias resolution, and fuzzy search.
"""

import difflib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience dependency
    def load_dotenv() -> bool:
        return False

from .models import XBRLFact
from .ticker_resolver import resolve_ticker

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XBRL_API_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
CACHE_DIR = Path("data/xbrl_cache")
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 hours

METRIC_ALIASES: dict[str, list[str]] = {
    # Income statement
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "net sales": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "net income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
        "NetIncomeLossAttributableToParent",
        "NetIncomeLossAttributableToParentDiluted",
    ],
    "net income attributable to shareholders": [
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
        "NetIncomeLossAttributableToParent",
        "NetIncomeLoss",
    ],
    "net income attributable to stockholders": [
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
        "NetIncomeLossAttributableToParent",
        "NetIncomeLoss",
    ],
    "eps": [
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
    ],
    "diluted eps": [
        "EarningsPerShareDiluted",
    ],
    "basic eps": [
        "EarningsPerShareBasic",
    ],
    "operating income": [
        "OperatingIncomeLoss",
    ],
    "gross profit": ["GrossProfit"],
    "cost of revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "cost of goods sold": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "research and development": [
        "ResearchAndDevelopmentExpense",
    ],
    "selling general and administrative": [
        "SellingGeneralAndAdministrativeExpense",
    ],
    "sga": [
        "SellingGeneralAndAdministrativeExpense",
    ],
    "income tax": [
        "IncomeTaxExpenseBenefit",
    ],
    "income before tax": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "interest expense": [
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestIncomeExpenseNet",
    ],
    "depreciation": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
    "depreciation and amortization": [
        "DepreciationAndAmortization",
        "DepreciationDepletionAndAmortization",
        "Depreciation",
    ],
    # Balance sheet
    "total assets": ["Assets"],
    "total current assets": ["AssetsCurrent"],
    "total liabilities": [
        "Liabilities",
    ],
    "total current liabilities": ["LiabilitiesCurrent"],
    "total liabilities and equity": [
        "LiabilitiesAndStockholdersEquity",
    ],
    "stockholders equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
    "cash and cash equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
    ],
    "inventory": [
        "InventoryNet",
        "InventoryFinishedGoodsNetOfReserves",
        "InventoryRawMaterials",
    ],
    "accounts receivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
    ],
    "accounts payable": [
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ],
    "goodwill": [
        "Goodwill",
    ],
    "intangible assets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    "net ppe": [
        "PropertyPlantAndEquipmentNet",
    ],
    "property plant and equipment": [
        "PropertyPlantAndEquipmentNet",
    ],
    "long term debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
    ],
    "total debt": [
        "LongTermDebt",
        "DebtCurrent",
    ],
    "short term debt": [
        "ShortTermBorrowings",
        "DebtCurrent",
        "LongTermDebtCurrent",
    ],
    "retained earnings": [
        "RetainedEarningsAccumulatedDeficit",
    ],
    # Cash flow statement
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CapitalExpenditureDiscontinuedOperations",
    ],
    "capital expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ],
    "operating cash flow": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "investing cash flow": [
        "NetCashProvidedByUsedInInvestingActivities",
    ],
    "financing cash flow": [
        "NetCashProvidedByUsedInFinancingActivities",
    ],
    "dividends": [
        "DividendsCash",
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "DividendsCommonStock",
    ],
    "share repurchase": [
        "PaymentsForRepurchaseOfCommonStock",
        "StockRepurchasedAndRetiredDuringPeriodValue",
    ],
    # Per-share and share data
    "shares outstanding": [
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    ],
    "weighted average shares": [
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
    "dividends per share": [
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ],
}

# ---------------------------------------------------------------------------
# Rate limiter — SEC allows 10 requests/second
# ---------------------------------------------------------------------------

_last_request_time = 0.0


def _rate_limit() -> None:
    """Enforce minimum 0.1s gap between SEC API requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 0.1:
        time.sleep(0.1 - elapsed)
    _last_request_time = time.time()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sec_headers() -> dict[str, str]:
    agent = os.getenv("SEC_USER_AGENT", "FinEdgar edgar_rag@example.com")
    return {"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}.json"


def _cache_is_fresh(path: Path) -> bool:
    """Return True if cache file exists and is younger than 24 hours."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_MAX_AGE_SECONDS


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _score_entry(entry: dict, year: int, period: str) -> tuple:
    end_dt = _parse_date(entry.get("end", ""))
    start_dt = _parse_date(entry.get("start", ""))
    filed_dt = _parse_date(entry.get("filed", ""))
    frame = str(entry.get("frame", ""))

    end_year_match = int(end_dt.year == year) if end_dt else 0
    end_quarter_bias = 0
    annual_duration_match = 0
    instant_year_end_match = 0

    if start_dt and end_dt and period == "FY":
        duration_days = (end_dt - start_dt).days + 1
        if 300 <= duration_days <= 380:
            annual_duration_match = 3
        elif 250 <= duration_days <= 450:
            annual_duration_match = 2
        elif 80 <= duration_days <= 110:
            annual_duration_match = 0
        else:
            annual_duration_match = 1
    elif end_dt and period == "FY":
        if end_dt.month in (10, 11, 12):
            instant_year_end_match = 2
        elif end_dt.month in (7, 8, 9):
            instant_year_end_match = 1

    if end_dt:
        if end_dt.month in (10, 11, 12):
            end_quarter_bias = 2
        elif end_dt.month in (7, 8, 9):
            end_quarter_bias = 1

    frame_bonus = 0
    if frame:
        if frame == f"CY{year}":
            frame_bonus = 3
        elif frame == f"CY{year}Q4I":
            frame_bonus = 3
        elif frame.startswith(f"CY{year}Q4"):
            frame_bonus = 2
        elif frame.startswith(f"CY{year}Q"):
            frame_bonus = 1
        elif frame.startswith(f"CY{year - 1}"):
            frame_bonus = -1
    else:
        frame_bonus = 2

    filed_ts = filed_dt.timestamp() if filed_dt else 0.0
    end_ts = end_dt.timestamp() if end_dt else 0.0

    return (
        end_year_match,
        annual_duration_match,
        instant_year_end_match,
        frame_bonus,
        end_quarter_bias,
        filed_ts,
        end_ts,
    )


def _concept_priority(metric: str, concept_name: str) -> int:
    metric_lower = metric.lower().strip()
    concept_lower = concept_name.lower()

    special_preferences = {
        "cost of goods sold": ["costofrevenue", "costofgoodsandservicessold", "costofgoodssold"],
        "dividends": ["dividendscash", "paymentsofdividends", "paymentsofdividendscommonstock"],
        "net income attributable to shareholders": [
            "netincomelossavailabletocommonstockholdersbasic",
            "netincomelossattributabletoparent",
            "netincomeloss",
        ],
        "net income attributable to stockholders": [
            "netincomelossavailabletocommonstockholdersbasic",
            "netincomelossattributabletoparent",
            "netincomeloss",
        ],
    }

    preferred = special_preferences.get(metric_lower)
    if preferred:
        for rank, key in enumerate(preferred):
            if key == concept_lower:
                return len(preferred) - rank

    if metric_lower.replace(" ", "") in concept_lower:
        return 2
    return 0


def _select_best_entry(entries: list[dict], year: int, period: str) -> dict | None:
    if not entries:
        return None
    return max(entries, key=lambda entry: _score_entry(entry, year, period))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_company_facts(ticker: str) -> dict:
    """Fetch full companyfacts JSON for *ticker*, using a local cache.

    The cache file is stored at ``data/xbrl_cache/{TICKER}.json`` and is
    re-fetched when older than 24 hours.
    """
    ticker = ticker.upper()
    cache = _cache_path(ticker)

    if _cache_is_fresh(cache):
        with open(cache, "r") as fh:
            return json.load(fh)

    cik, _name = resolve_ticker(ticker)
    url = XBRL_API_URL.format(cik=cik)

    _rate_limit()
    resp = requests.get(url, headers=_sec_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache, "w") as fh:
        json.dump(data, fh)

    return data


def get_metric(
    ticker: str,
    concept: str,
    year: int,
    period: str = "FY",
) -> XBRLFact | None:
    """Return a single :class:`XBRLFact` for *concept* in *year*/*period*.

    If *concept* is a common English name (e.g. ``"revenue"``), resolve it
    via :data:`METRIC_ALIASES` and try each XBRL concept in order.

    For ``period="FY"`` the filter uses ``form == "10-K"``; for quarterly
    periods (``"Q1"``, ``"Q2"``, etc.) it uses ``form == "10-Q"``.
    """
    # Determine which XBRL concept names to try.
    concept_lower = concept.lower()
    if concept_lower in METRIC_ALIASES:
        concepts_to_try = METRIC_ALIASES[concept_lower]
    else:
        concepts_to_try = [concept]

    data = fetch_company_facts(ticker)
    us_gaap = data.get("facts", {}).get("us-gaap", {})

    target_form = "10-K" if period == "FY" else "10-Q"

    ranked_candidates: list[tuple[tuple, str, str, dict]] = []
    for concept_name in concepts_to_try:
        concept_data = us_gaap.get(concept_name)
        if concept_data is None:
            continue

        units = concept_data.get("units", {})
        # Try USD first, then USD/shares (for EPS), then shares
        for unit_key in ("USD", "USD/shares", "shares", "pure"):
            entries = units.get(unit_key)
            if entries is None:
                continue

            # Collect all candidate facts for this concept/year/period
            candidates = [
                entry for entry in entries
                if (
                    entry.get("fy") == year
                    and entry.get("fp") == period
                    and entry.get("form") == target_form
                )
            ]
            if not candidates:
                continue

            # Disambiguate: prefer the fact whose end date matches the
            # fiscal year.  10-K filings include comparative periods
            # (e.g. the 2018 10-K reports 2016, 2017, 2018 data), all
            # tagged with fy=2018.  The correct current-year fact has
            # end date in the target fiscal year.
            best = _select_best_entry(candidates, year, period)
            if best is None:
                continue

            ranked_candidates.append(
                (
                    (_concept_priority(concept, concept_name),) + _score_entry(best, year, period),
                    concept_name,
                    unit_key,
                    best,
                )
            )

    if ranked_candidates:
        _score, concept_name, unit_key, best = max(ranked_candidates, key=lambda item: item[0])
        return XBRLFact(
            concept=concept_name,
            value=best["val"],
            unit=unit_key,
            fiscal_year=year,
            fiscal_period=best.get("fp", period),
            filed=best.get("filed", ""),
            form=best.get("form", ""),
        )

    return None


def search_metric(
    ticker: str,
    query: str,
    year: int,
    period: str = "FY",
) -> list[XBRLFact]:
    """Fuzzy-search across all us-gaap concepts for *ticker*/*year*.

    Uses :func:`difflib.get_close_matches` to find concept names similar
    to *query*, then returns matching facts.
    """
    data = fetch_company_facts(ticker)
    us_gaap = data.get("facts", {}).get("us-gaap", {})

    all_concepts = list(us_gaap.keys())
    matches = difflib.get_close_matches(query, all_concepts, n=10, cutoff=0.4)

    results: list[XBRLFact] = []
    for concept_name in matches:
        concept_data = us_gaap[concept_name]
        units = concept_data.get("units", {})
        for unit_key, entries in units.items():
            candidates = [
                entry for entry in entries
                if (
                    entry.get("fy") == year
                    and entry.get("fp") == period
                    and entry.get("form") in ("10-K", "10-Q")
                )
            ]
            best = _select_best_entry(candidates, year, period)
            if best is None:
                continue
            results.append(
                XBRLFact(
                    concept=concept_name,
                    value=best["val"],
                    unit=unit_key,
                    fiscal_year=year,
                    fiscal_period=best.get("fp", period),
                    filed=best.get("filed", ""),
                    form=best.get("form", ""),
                )
            )
    return results


def resolve_metric(query: str) -> list[str]:
    """Resolve a natural-language metric name to XBRL concept names.

    Performs an exact (case-insensitive) lookup in :data:`METRIC_ALIASES`
    first, then falls back to fuzzy matching against the alias keys.

    Returns a list of XBRL concept names to try, or an empty list if
    nothing matches.
    """
    query_lower = query.lower().strip()

    # Exact match
    if query_lower in METRIC_ALIASES:
        return METRIC_ALIASES[query_lower]

    # Fuzzy match against alias keys
    close = difflib.get_close_matches(
        query_lower, list(METRIC_ALIASES.keys()), n=3, cutoff=0.5
    )
    if close:
        # Return concepts for the best match
        return METRIC_ALIASES[close[0]]

    return []
