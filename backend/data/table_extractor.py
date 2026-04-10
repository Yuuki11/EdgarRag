"""Extract HTML financial tables into readable markdown format.

Handles SEC EDGAR 10-K table conventions:
- Currency symbols ($) in separate cells
- colspan headers
- Negative numbers in parentheses
- Empty spacer cells
- Alternating row background colors
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import Tag


def _cell_text(cell: "Tag") -> str:
    """Extract clean text from a table cell."""
    return cell.get_text(strip=True)


def _get_colspan(cell: "Tag") -> int:
    """Get colspan attribute value, defaulting to 1."""
    try:
        return int(cell.get("colspan", 1))
    except (ValueError, TypeError):
        return 1


def _is_currency_symbol(text: str) -> bool:
    """Check if text is just a currency symbol."""
    return text.strip() in ("$", "€", "£", "¥")


def _is_pct_symbol(text: str) -> bool:
    """Check if text is just a percentage symbol."""
    return text.strip() == "%"


def _is_empty_or_spacer(text: str) -> bool:
    """Check if text is empty or whitespace-only."""
    return not text.strip() or text.strip() in ("\xa0", "\u00a0", "—", "–")


def _merge_currency_cells(cells: list[str]) -> list[str]:
    """Merge standalone currency symbols with adjacent number cells.

    SEC filings put "$" in its own <td>, followed by the number.
    Example: ["Cash", "$", "29,965", "", "", "$", "23,646", ""]
    Becomes: ["Cash", "$29,965", "$23,646"]
    """
    if not cells:
        return cells

    merged: list[str] = []
    i = 0
    while i < len(cells):
        text = cells[i].strip()

        if _is_currency_symbol(text) and i + 1 < len(cells):
            # Merge $ with next non-empty cell
            next_text = cells[i + 1].strip()
            if next_text and not _is_empty_or_spacer(next_text):
                merged.append(f"{text}{next_text}")
                i += 2
                continue

        if _is_pct_symbol(text) and merged:
            # Append % to previous cell
            merged[-1] = merged[-1] + "%"
            i += 1
            continue

        if not _is_empty_or_spacer(text):
            merged.append(text)
        i += 1

    return merged


def _is_header_row(row: "Tag", row_index: int) -> bool:
    """Detect if a row is a header row."""
    # Has <th> elements
    if row.find_all("th"):
        return True

    # First or second row is often a header
    if row_index <= 1:
        cells = row.find_all(["td", "th"])
        # Check for bold text (common in SEC filings)
        for cell in cells:
            if cell.find("b") or cell.find("strong"):
                return False  # Bold in data rows is section headers, not table headers
            span = cell.find("span")
            if span and span.get("style") and "font-weight:700" in span.get("style", ""):
                text = cell.get_text(strip=True)
                # If it contains a year-like pattern, it's a header
                if re.search(r"20\d{2}|19\d{2}", text):
                    return True

    return False


def _is_section_header_row(merged_cells: list[str]) -> bool:
    """Detect rows that are section headers within a table (e.g., 'ASSETS:', 'Current assets:')."""
    if len(merged_cells) == 1:
        text = merged_cells[0].strip()
        # Single-cell rows that end with ":" are section headers
        if text.endswith(":") or text.endswith(":"):
            return True
        # ALL-CAPS single-cell rows
        if text.isupper() and len(text) > 3:
            return True
    return False


def html_table_to_markdown(table: "Tag") -> str:
    """Convert an HTML table element to a readable markdown-style table.

    Args:
        table: BeautifulSoup Tag for a <table> element

    Returns:
        Markdown-formatted table string, or empty string if table is layout-only
    """
    rows = table.find_all("tr")
    if len(rows) < 2:
        return ""

    parsed_rows: list[list[str]] = []
    header_indices: list[int] = []

    for row_idx, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        raw_texts: list[str] = []

        for cell in cells:
            text = _cell_text(cell)
            colspan = _get_colspan(cell)
            raw_texts.append(text)
            # For colspan > 1, the text belongs to this one cell
            # Don't add empty cells for colspan — just note the text

        merged = _merge_currency_cells(raw_texts)

        if not merged:
            continue

        # Detect header rows
        if _is_header_row(row, row_idx):
            header_indices.append(len(parsed_rows))

        # Detect section header rows (single-cell like "ASSETS:")
        if _is_section_header_row(merged):
            # Keep as a single text line, not a table row
            parsed_rows.append(merged)
            continue

        parsed_rows.append(merged)

    if not parsed_rows:
        return ""

    # Filter out purely empty tables
    non_empty = [r for r in parsed_rows if any(c.strip() for c in r)]
    if len(non_empty) < 2:
        return ""

    # Build markdown output
    lines: list[str] = []
    for row_idx, cells in enumerate(parsed_rows):
        if len(cells) == 1:
            # Section header row — output as bold text
            lines.append(f"**{cells[0]}**")
            continue

        line = " | ".join(cells)
        lines.append(line)

        # Add separator after header rows
        if row_idx in header_indices:
            sep = " | ".join(["---"] * len(cells))
            lines.append(sep)

    result = "\n".join(lines)

    # Final quality check: if the table has very little actual data, skip it
    data_cells = sum(
        1 for row in parsed_rows for c in row
        if c.strip() and not _is_empty_or_spacer(c) and len(c.strip()) > 0
    )
    if data_cells < 4:
        return ""

    return result
