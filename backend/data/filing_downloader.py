"""Download SEC filings from EDGAR."""

import logging
import os
import time
from pathlib import Path

import requests
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience dependency
    def load_dotenv() -> bool:
        return False

from backend.data.ticker_resolver import resolve_ticker

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting – SEC allows 10 req/s, space requests by >= 0.1 s
# ---------------------------------------------------------------------------
_last_request_time: float = 0.0


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 0.1:
        time.sleep(0.1 - elapsed)
    _last_request_time = time.time()


def _get_user_agent() -> str:
    ua = os.getenv("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError(
            "SEC_USER_AGENT environment variable is not set. "
            "Set it to something like 'Your Name your@email.com'."
        )
    return ua


_FILINGS_DIR = Path("data/filings")

# SEC EDGAR base URLs
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
_SUBMISSIONS_ARCHIVE_BASE = "https://data.sec.gov/submissions"


def _sanitize_form_name(form: str) -> str:
    return form.replace("/", "-").replace(" ", "_")


def _build_filing_url(cik: str, accession: str, primary_doc: str) -> str:
    accession_no_dash = accession.replace("-", "")
    return f"{_ARCHIVES_BASE}/{cik.lstrip('0')}/{accession_no_dash}/{primary_doc}"


def _iter_filing_rows(filings: dict[str, list], cik: str) -> list[dict]:
    forms = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    filing_dates = filings.get("filingDate", [])
    report_dates = filings.get("reportDate", [])
    primary_docs = filings.get("primaryDocument", [])

    rows: list[dict] = []
    for i, form in enumerate(forms):
        accession = accessions[i] if i < len(accessions) else ""
        if not accession:
            continue
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""
        filing_date = filing_dates[i] if i < len(filing_dates) else ""
        report_date = report_dates[i] if i < len(report_dates) else ""
        url = _build_filing_url(cik, accession, primary_doc)
        doc_id = f"{_sanitize_form_name(form)}_{accession}"
        rows.append(
            {
                "form": form,
                "accession": accession,
                "filing_date": filing_date,
                "report_date": report_date,
                "primary_doc": primary_doc,
                "url": url,
                "document_id": doc_id,
            }
        )
    return rows


def _filing_matches_year(form: str, filing_date: str, report_date: str, year: int) -> bool:
    try:
        if form in {"10-K", "10-Q"} and report_date:
            return int(report_date[:4]) == year
        if filing_date:
            return int(filing_date[:4]) == year
        if report_date:
            return int(report_date[:4]) == year
    except (TypeError, ValueError):
        return False
    return False


def _filing_cache_path(ticker: str, year: int, filing: dict) -> Path:
    ticker_upper = ticker.strip().upper()
    form_dir = _sanitize_form_name(filing["form"])
    filename = filing.get("primary_doc") or f"{filing['document_id']}.txt"
    if not Path(filename).suffix:
        filename = f"{filename}.txt"

    if filing["form"] == "10-K":
        return _FILINGS_DIR / ticker_upper / str(year) / "10-K.htm"
    return _FILINGS_DIR / ticker_upper / str(year) / form_dir / filing["document_id"] / filename


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_filing_index(ticker: str) -> dict:
    """Fetch the submissions index for a company from SEC EDGAR.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g. "AAPL").

    Returns
    -------
    dict
        The full submissions JSON from SEC.
    """
    cik, _ = resolve_ticker(ticker)
    url = _SUBMISSIONS_URL.format(cik=cik)

    _rate_limit()
    headers = {"User-Agent": _get_user_agent()}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fetch_submission_file(name: str) -> dict:
    """Fetch an archived submissions file referenced by the main index."""
    _rate_limit()
    headers = {"User-Agent": _get_user_agent()}
    url = f"{_SUBMISSIONS_ARCHIVE_BASE}/{name}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _merged_filing_history(index: dict) -> dict[str, list]:
    """Merge recent and archived SEC filing arrays into one record set."""
    merged = {
        key: list(value)
        for key, value in index.get("filings", {}).get("recent", {}).items()
        if isinstance(value, list)
    }

    for file_info in index.get("filings", {}).get("files", []) or []:
        name = file_info.get("name")
        if not name:
            continue
        archive = _fetch_submission_file(name)
        archive_recent = archive.get("filings", {}).get("recent", archive)
        for key, value in archive_recent.items():
            if not isinstance(value, list):
                continue
            merged.setdefault(key, []).extend(value)

    return merged


def find_10k_filing(ticker: str, year: int) -> dict | None:
    """Find the 10-K filing metadata for a specific fiscal year.

    Searches ``recentFilings`` in the SEC submissions index for a 10-K
    (not 10-K/A) whose ``reportDate`` falls in the given fiscal year.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol.
    year : int
        Fiscal year to match (e.g. 2023).

    Returns
    -------
    dict | None
        ``{"accession": str, "filing_date": str, "primary_doc": str, "url": str}``
        or ``None`` if no matching filing is found.
    """
    filings = find_filings(ticker, year, forms=("10-K",), limit_per_form=1)
    return filings[0] if filings else None


def find_filings(
    ticker: str,
    year: int,
    forms: tuple[str, ...] = ("10-K",),
    limit_per_form: int | None = None,
) -> list[dict]:
    """Find filings for a ticker/year across one or more SEC form types."""
    index = get_filing_index(ticker)
    cik, _ = resolve_ticker(ticker)
    filings = _merged_filing_history(index)
    if not filings:
        return []

    requested_forms = {form.upper() for form in forms}
    rows = _iter_filing_rows(filings, cik)

    results: list[dict] = []
    per_form_counts: dict[str, int] = {}
    for row in rows:
        form = str(row["form"]).upper()
        if form not in requested_forms:
            continue
        if form.endswith("/A"):
            continue
        if not _filing_matches_year(form, row.get("filing_date", ""), row.get("report_date", ""), year):
            continue
        if limit_per_form is not None and per_form_counts.get(form, 0) >= limit_per_form:
            continue
        per_form_counts[form] = per_form_counts.get(form, 0) + 1
        results.append(row)

    results.sort(key=lambda item: (item["form"], item.get("filing_date", ""), item.get("accession", "")))
    return results


def download_filing(ticker: str, year: int, filing: dict, force: bool = False) -> str:
    """Download a filing record returned by find_filings/find_10k_filing."""
    cache_path = _filing_cache_path(ticker, year, filing)
    if cache_path.exists() and not force:
        logger.info("Using cached %s for %s %s: %s", filing["form"], ticker.upper(), year, cache_path)
        return str(cache_path)

    _rate_limit()
    headers = {"User-Agent": _get_user_agent()}
    resp = requests.get(filing["url"], headers=headers, timeout=60)
    resp.raise_for_status()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(resp.content)
    logger.info("Downloaded %s for %s FY%d -> %s", filing["form"], ticker.upper(), year, cache_path)
    return str(cache_path)


def download_10k(ticker: str, year: int, force: bool = False) -> str:
    """Download the 10-K HTML for a given ticker and fiscal year.

    The file is cached to ``data/filings/{ticker}/{year}/10-K.htm``.
    Subsequent calls return the cached path unless *force* is ``True``.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol.
    year : int
        Fiscal year.
    force : bool, optional
        Re-download even if a cached copy exists.

    Returns
    -------
    str
        Local file path of the downloaded 10-K HTML.

    Raises
    ------
    FileNotFoundError
        If no 10-K filing is found for the given ticker/year.
    """
    filing = find_10k_filing(ticker, year)
    if filing is None:
        raise FileNotFoundError(
            f"No 10-K filing found for {ticker.strip().upper()} FY{year}."
        )
    return download_filing(ticker, year, filing, force=force)


def download_filings(
    ticker: str,
    year: int,
    forms: tuple[str, ...],
    force: bool = False,
    limit_per_form: int | None = None,
) -> list[dict]:
    """Download all matching filings for the requested year/forms."""
    filings = find_filings(ticker, year, forms=forms, limit_per_form=limit_per_form)
    downloaded: list[dict] = []
    for filing in filings:
        try:
            path = download_filing(ticker, year, filing, force=force)
        except requests.RequestException as exc:
            logger.warning("Failed to download %s for %s FY%d: %s", filing["form"], ticker.upper(), year, exc)
            continue
        downloaded.append({**filing, "local_path": path})
    return downloaded


def download_all_10ks(ticker: str) -> list[str]:
    """Download all available 10-K filings from recentFilings.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol.

    Returns
    -------
    list[str]
        List of local file paths for each downloaded 10-K.
    """
    index = get_filing_index(ticker)
    cik, _ = resolve_ticker(ticker)
    filings_index = _merged_filing_history(index)
    if not filings_index:
        return []

    rows = _iter_filing_rows(filings_index, cik)
    seen_years: set[int] = set()
    paths: list[str] = []
    for filing in rows:
        if filing["form"] != "10-K" or filing["form"].endswith("/A"):
            continue
        report_date = filing.get("report_date", "")
        if not report_date:
            continue
        year = int(report_date[:4])
        if year in seen_years:
            continue
        seen_years.add(year)
        try:
            paths.append(download_filing(ticker, year, filing))
        except requests.RequestException as exc:
            logger.warning("Failed to download %s FY%d: %s", ticker.upper(), year, exc)
    return paths
