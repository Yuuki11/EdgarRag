"""Shared data structures for SEC filings, chunks, companies, and XBRL facts."""

from dataclasses import dataclass, field
from enum import Enum


class Section(str, Enum):
    ITEM_1 = "item_1"
    ITEM_1A = "item_1a"
    ITEM_7 = "item_7"
    ITEM_7A = "item_7a"
    ITEM_8 = "item_8"


SECTION_NAMES = {
    Section.ITEM_1: "Business",
    Section.ITEM_1A: "Risk Factors",
    Section.ITEM_7: "Management's Discussion and Analysis",
    Section.ITEM_7A: "Quantitative and Qualitative Disclosures About Market Risk",
    Section.ITEM_8: "Financial Statements and Supplementary Data",
}


@dataclass
class FilingChunk:
    text: str
    ticker: str
    year: int
    document_id: str
    section: str
    section_name: str
    chunk_index: int
    filing_date: str
    form_type: str
    source_url: str
    token_count: int
    chunk_type: str = "text"  # "text" or "table"


@dataclass
class CompanyInfo:
    ticker: str
    cik: str
    name: str
    sector: str
    available_years: list[int] = field(default_factory=list)


@dataclass
class XBRLFact:
    concept: str
    value: float
    unit: str
    fiscal_year: int
    fiscal_period: str
    filed: str
    form: str
