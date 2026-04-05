"""Ticker to CIK resolution using SEC's company_tickers.json."""

import json
import os
import time
from pathlib import Path

import requests
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience dependency
    def load_dotenv() -> bool:
        return False

load_dotenv()

# ---------------------------------------------------------------------------
# Rate limiting – SEC allows 10 req/s, so we space requests by >= 0.1 s
# ---------------------------------------------------------------------------
_last_request_time: float = 0.0


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 0.1:
        time.sleep(0.1 - elapsed)
    _last_request_time = time.time()


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------
class TickerNotFoundError(Exception):
    """Raised when a ticker cannot be resolved to a CIK."""


# ---------------------------------------------------------------------------
# Internal cache
# ---------------------------------------------------------------------------
_CACHE_PATH = Path("data/company_tickers.json")
_OVERRIDES_PATH = Path("data/company_overrides.json")
_ticker_lookup: dict[str, dict[str, str]] | None = None


def _get_user_agent() -> str:
    ua = os.getenv("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError(
            "SEC_USER_AGENT environment variable is not set. "
            "Set it to something like 'Your Name your@email.com'."
        )
    return ua


def _download_tickers() -> dict:
    """Download company_tickers.json from SEC and cache locally."""
    _rate_limit()
    url = "https://www.sec.gov/files/company_tickers.json"
    headers = {"User-Agent": _get_user_agent()}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _load_tickers() -> dict[str, dict[str, str]]:
    """Load (or download) the ticker lookup dict."""
    global _ticker_lookup
    if _ticker_lookup is not None:
        return _ticker_lookup

    # Try cached file first
    if _CACHE_PATH.exists():
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    else:
        raw = _download_tickers()

    # Build lookup: {TICKER_UPPER: {"cik": "0000320193", "name": "Apple Inc."}}
    lookup: dict[str, dict[str, str]] = {}
    for _key, entry in raw.items():
        ticker = str(entry["ticker"]).upper()
        cik = str(entry["cik_str"]).zfill(10)
        name = entry["title"]
        lookup[ticker] = {"cik": cik, "name": name}

    if _OVERRIDES_PATH.exists():
        overrides = json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
        for entry in overrides:
            ticker = str(entry["ticker"]).upper()
            cik = str(entry["cik"]).zfill(10)
            name = str(entry["name"])
            lookup[ticker] = {"cik": cik, "name": name}

    _ticker_lookup = lookup
    return _ticker_lookup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def resolve_ticker(ticker: str) -> tuple[str, str]:
    """Resolve a stock ticker to (cik, company_name).

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (case-insensitive).

    Returns
    -------
    tuple[str, str]
        (cik zero-padded to 10 digits, company name)

    Raises
    ------
    TickerNotFoundError
        If the ticker is not found in the SEC database.
    """
    lookup = _load_tickers()
    key = ticker.strip().upper()
    if key not in lookup:
        raise TickerNotFoundError(f"Ticker '{ticker}' not found in SEC database.")
    entry = lookup[key]
    return entry["cik"], entry["name"]
