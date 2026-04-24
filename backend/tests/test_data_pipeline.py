"""Tests for the SEC EDGAR data pipeline modules.

All SEC API calls are mocked so tests run offline and quickly.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so ``backend.data`` imports work.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.data.models import FilingChunk, Section, SECTION_NAMES
from backend.data.xbrl_fetcher import resolve_metric, METRIC_ALIASES


# ===================================================================
# 1. test_ticker_resolver
# ===================================================================

@patch("backend.data.ticker_resolver._load_tickers")
def test_ticker_resolver(mock_load):
    """Mock SEC API and verify 'AAPL' resolves to CIK '0000320193'."""
    mock_load.return_value = {
        "AAPL": {"cik": "0000320193", "name": "Apple Inc."},
        "MSFT": {"cik": "0000789019", "name": "Microsoft Corporation"},
    }

    from backend.data.ticker_resolver import resolve_ticker

    cik, name = resolve_ticker("AAPL")
    assert cik == "0000320193"
    assert name == "Apple Inc."


@patch("backend.data.ticker_resolver._OVERRIDES_PATH")
@patch("backend.data.ticker_resolver._CACHE_PATH")
def test_ticker_resolver_manual_override(mock_cache_path, mock_overrides_path, tmp_path):
    """Manual overrides should resolve historical or missing tickers."""
    import backend.data.ticker_resolver as resolver

    mock_cache_path.exists.return_value = True
    mock_cache_path.read_text.return_value = json.dumps(
        {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}
    )

    overrides_path = tmp_path / "company_overrides.json"
    overrides_path.write_text(
        json.dumps(
            [
                {
                    "ticker": "ATVI",
                    "cik": "0000718877",
                    "name": "Activision Blizzard, Inc.",
                }
            ]
        ),
        encoding="utf-8",
    )
    mock_overrides_path.exists.return_value = True
    mock_overrides_path.read_text.side_effect = overrides_path.read_text
    resolver._ticker_lookup = None

    cik, name = resolver.resolve_ticker("ATVI")
    assert cik == "0000718877"
    assert name == "Activision Blizzard, Inc."

    resolver._ticker_lookup = None


# ===================================================================
# 2. test_xbrl_fetcher_apple_revenue
# ===================================================================

@patch("backend.data.xbrl_fetcher.fetch_company_facts")
def test_xbrl_fetcher_apple_revenue(mock_facts):
    """Mock companyfacts API and verify revenue extraction for AAPL FY2023."""
    mock_facts.return_value = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "val": 383_285_000_000,
                                "filed": "2023-11-03",
                            },
                        ]
                    }
                }
            }
        }
    }

    from backend.data.xbrl_fetcher import get_metric

    fact = get_metric("AAPL", "revenue", 2023)
    assert fact is not None
    assert fact.value == 383_285_000_000
    assert fact.concept == "Revenues"
    assert fact.fiscal_year == 2023
    assert fact.form == "10-K"


@patch("backend.data.xbrl_fetcher.fetch_company_facts")
def test_xbrl_fetcher_prefers_full_year_fact_over_quarter_in_10k(mock_facts):
    """Annual lookups should prefer the true FY fact over quarterly comparatives in the same 10-K."""
    mock_facts.return_value = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "start": "2019-01-01",
                                "end": "2019-03-31",
                                "val": 3_561_000_000,
                                "fy": 2019,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2020-01-31",
                            },
                            {
                                "start": "2019-01-01",
                                "end": "2019-12-31",
                                "val": 11_588_000_000,
                                "fy": 2019,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2020-01-31",
                            },
                        ]
                    }
                }
            }
        }
    }

    from backend.data.xbrl_fetcher import get_metric

    fact = get_metric("AMZN", "net income", 2019)
    assert fact is not None
    assert fact.value == 11_588_000_000


# ===================================================================
# 3. test_metric_alias_resolution
# ===================================================================

def test_metric_alias_resolution():
    """Verify 'revenue' resolves to a list containing 'Revenues'."""
    concepts = resolve_metric("revenue")
    assert isinstance(concepts, list)
    assert "Revenues" in concepts

    # Also verify fuzzy matching works for a close variant.
    concepts2 = resolve_metric("net income")
    assert "NetIncomeLoss" in concepts2


# ===================================================================
# 4. test_section_parser_apple
# ===================================================================

@patch("backend.data.section_parser._parse_with_sec_parser", return_value=None)
def test_section_parser_apple(mock_sp, tmp_path):
    """Mock a simple 10-K HTML with all 5 sections, verify parsing."""
    html = _build_mock_10k_html("Apple Inc.", style="standard")
    filepath = tmp_path / "apple_10k.htm"
    filepath.write_text(html, encoding="utf-8")

    from backend.data.section_parser import parse_10k_sections

    sections = parse_10k_sections(str(filepath))

    for key in ["item_1", "item_1a", "item_7", "item_7a", "item_8"]:
        assert sections.get(key) is not None, f"Section {key} was not found"
        assert len(sections[key]) > 1000, f"Section {key} too short"


# ===================================================================
# 5. test_section_parser_jpmorgan
# ===================================================================

@patch("backend.data.section_parser._parse_with_sec_parser", return_value=None)
def test_section_parser_jpmorgan(mock_sp, tmp_path):
    """Mock a different formatting style (dash separators) and verify parsing."""
    html = _build_mock_10k_html("JPMorgan Chase & Co.", style="dash")
    filepath = tmp_path / "jpm_10k.htm"
    filepath.write_text(html, encoding="utf-8")

    from backend.data.section_parser import parse_10k_sections

    sections = parse_10k_sections(str(filepath))

    for key in ["item_1", "item_1a", "item_7", "item_7a", "item_8"]:
        assert sections.get(key) is not None, f"Section {key} was not found"


# ===================================================================
# 6. test_chunker_respects_size_limit
# ===================================================================

def test_chunker_respects_size_limit():
    """Create text > 512 tokens and verify no chunk exceeds the limit."""
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")

    # Build a long text (~2000 tokens).
    long_text = " ".join(["The company reported strong financial results."] * 300)
    assert len(enc.encode(long_text)) > 512

    from backend.data.chunker import chunk_section

    chunks = chunk_section(
        text=long_text,
        ticker="TEST",
        year=2023,
        document_id="10-K_2023_TEST",
        section="item_7",
        section_name="MD&A",
        filing_date="2024-02-01",
        source_url="https://example.com/filing",
        chunk_size=512,
        chunk_overlap=64,
    )

    assert len(chunks) > 0
    for chunk in chunks:
        token_count = len(enc.encode(chunk.text))
        assert token_count <= 512, (
            f"Chunk {chunk.chunk_index} has {token_count} tokens, exceeds 512"
        )


# ===================================================================
# 7. test_chunker_preserves_metadata
# ===================================================================

def test_chunker_preserves_metadata():
    """Verify chunk metadata matches input arguments."""
    # Build text long enough to not be filtered (>100 tokens).
    text = " ".join(["Financial performance was strong during the period."] * 50)

    from backend.data.chunker import chunk_section

    chunks = chunk_section(
        text=text,
        ticker="AAPL",
        year=2023,
        document_id="10-K_2023_AAPL",
        section="item_1",
        section_name="Business",
        filing_date="2023-11-03",
        source_url="https://sec.gov/filing/aapl",
        chunk_size=512,
        chunk_overlap=64,
    )

    assert len(chunks) >= 1
    c = chunks[0]
    assert c.ticker == "AAPL"
    assert c.year == 2023
    assert c.document_id == "10-K_2023_AAPL"
    assert c.section == "item_1"
    assert c.section_name == "Business"
    assert c.filing_date == "2023-11-03"
    assert c.form_type == "10-K"
    assert c.source_url == "https://sec.gov/filing/aapl"
    assert c.chunk_index == 0
    assert c.token_count > 0


# ===================================================================
# 8. test_chunker_minimum_size
# ===================================================================

def test_chunker_minimum_size():
    """Verify chunks below 100 tokens are filtered out."""
    # Text that is only ~10 tokens — should produce zero chunks.
    short_text = "This is a very short section."

    from backend.data.chunker import chunk_section

    chunks = chunk_section(
        text=short_text,
        ticker="TEST",
        year=2023,
        document_id="10-K_2023_TEST",
        section="item_8",
        section_name="Financial Statements",
        filing_date="2024-01-15",
        source_url="https://example.com",
        chunk_size=512,
        chunk_overlap=64,
    )

    assert len(chunks) == 0, "Short text should produce no chunks"


# ===================================================================
# Helpers
# ===================================================================

def _build_mock_10k_html(company_name: str, style: str = "standard") -> str:
    """Build a fake 10-K HTML document with all 5 target sections.

    *style* controls the header formatting:
    - ``"standard"``: ``Item 1. Business``
    - ``"dash"``: ``Item 1 - Business``
    """
    sep = ". " if style == "standard" else " - "
    filler = ("<p>" + "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 30 + "</p>\n") * 10

    sections = [
        (f"Item 1{sep}Business", filler),
        (f"Item 1A{sep}Risk Factors", filler),
        (f"Item 7{sep}Management's Discussion and Analysis", filler),
        (f"Item 7A{sep}Quantitative and Qualitative Disclosures About Market Risk", filler),
        (f"Item 8{sep}Financial Statements and Supplementary Data", filler),
        (f"Item 9{sep}Changes in and Disagreements with Accountants", "<p>None.</p>"),
    ]

    body_parts = [f"<h2>{title}</h2>\n{content}" for title, content in sections]
    body = "\n".join(body_parts)

    return f"""<html><head><title>{company_name} 10-K</title></head>
<body>
<h1>{company_name} Annual Report (Form 10-K)</h1>
{body}
</body></html>"""
