"""
10-K Section Extraction Module.

Parses SEC 10-K filing HTML files into individual sections
(Item 1, 1A, 7, 7A, 8). Uses the sec-parser library as the primary
approach, falling back to regex-based extraction when sec-parser
cannot handle the filing format.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString

from backend.data.models import Section
from backend.data.table_extractor import html_table_to_markdown

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Target sections we want to extract from 10-K filings
# ---------------------------------------------------------------------------
_TARGET_SECTIONS: list[str] = [s.value for s in Section]

# ---------------------------------------------------------------------------
# Regex patterns for the fallback parser.
# Each key maps to a list of patterns that match the section header.
# Patterns are tried in order; the first match wins.
# ---------------------------------------------------------------------------
SECTION_PATTERNS: dict[str, list[str]] = {
    "item_1": [
        r"(?i)(?:item|ITEM)\s*1[\.\s\:\-\u2014\u2013]+(?:business|BUSINESS)",
        r"(?i)PART\s+I\s*[\n\r]+\s*Item\s+1",
    ],
    "item_1a": [
        r"(?i)(?:item|ITEM)\s*1A[\.\s\:\-\u2014\u2013]+(?:risk\s+factors|RISK\s+FACTORS)",
        r"(?i)Item\s+1A\s*[\.\-\u2014\u2013]\s*Risk",
    ],
    "item_7": [
        r"(?i)(?:item|ITEM)\s*7[\.\s\:\-\u2014\u2013]+(?:management|MANAGEMENT)",
        r"(?i)Item\s+7\s*[\.\-\u2014\u2013]\s*Management",
    ],
    "item_7a": [
        r"(?i)(?:item|ITEM)\s*7A[\.\s\:\-\u2014\u2013]+(?:quantitative|QUANTITATIVE)",
    ],
    "item_8": [
        r"(?i)(?:item|ITEM)\s*8[\.\s\:\-\u2014\u2013]+(?:financial\s+statements|FINANCIAL\s+STATEMENTS)",
    ],
}

# Broader patterns that match *any* 10-K item header.  Used for detecting
# section boundaries so we know where a given section ends.
_ALL_ITEM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?i)(?:item|ITEM)\s*(\d+[A-Za-z]?)[\.\s\:\-\u2014\u2013]+"
    ),
]

# Minimum character count for extracted section content.  Anything shorter
# is almost certainly a Table of Contents entry or a page header repeat.
_MIN_SECTION_LENGTH = 1000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_10k_sections(filepath: str) -> dict[str, str | None]:
    """
    Parse a 10-K filing into sections.

    Returns a dict mapping section keys to text content::

        {"item_1": "...", "item_1a": "...", "item_7": "...",
         "item_7a": "...", "item_8": "..."}

    If a section cannot be found the value will be ``None``.
    The function never raises on parse failures — it logs warnings instead.
    """
    try:
        html_text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    except Exception:
        logger.exception("Failed to read filing at %s", filepath)
        return {s: None for s in _TARGET_SECTIONS}

    # ------------------------------------------------------------------
    # Attempt 1: sec-parser library
    # ------------------------------------------------------------------
    sections = _parse_with_sec_parser(html_text)
    if sections is not None and _has_enough_sections(sections):
        logger.info("sec-parser successfully extracted sections from %s", filepath)
        return sections

    # ------------------------------------------------------------------
    # Attempt 2: Regex fallback
    # ------------------------------------------------------------------
    logger.info("Falling back to regex parser for %s", filepath)
    sections = _parse_with_regex(html_text)
    return sections


# ---------------------------------------------------------------------------
# sec-parser approach
# ---------------------------------------------------------------------------

def _parse_with_sec_parser(html_text: str) -> dict[str, str | None] | None:
    """
    Use the ``sec-parser`` library to extract sections.

    Returns *None* if sec-parser is unavailable or raises an error, so the
    caller can fall back to regex.
    """
    try:
        import sec_parser as sp
    except ImportError:
        logger.warning("sec-parser is not installed; skipping tree-based parsing")
        return None

    try:
        # sec-parser ships an Edgar10QParser which also handles 10-K HTML
        # reasonably well — it extracts top-level tags and identifies
        # section markers via regex on element text.
        parser = sp.Edgar10QParser()
        elements = parser.parse(html_text)
        tree = sp.TreeBuilder().build(elements)
    except Exception:
        logger.warning("sec-parser failed to build semantic tree", exc_info=True)
        return None

    return _extract_sections_from_tree(tree)


# Map from a normalised item key (e.g. "1a") to our section key.
_ITEM_KEY_MAP: dict[str, str] = {
    "1": "item_1",
    "1a": "item_1a",
    "7": "item_7",
    "7a": "item_7a",
    "8": "item_8",
}

# Regex to pull the item number from a TopSectionTitle text.
_ITEM_NUM_RE = re.compile(r"(?i)item\s*(\d+[A-Za-z]?)")


def _extract_sections_from_tree(tree) -> dict[str, str | None]:
    """Walk the semantic tree and collect text for target sections."""
    import sec_parser as sp

    sections: dict[str, str | None] = {s: None for s in _TARGET_SECTIONS}

    # Collect all nodes in order so we can grab text between section markers.
    all_nodes: list = list(tree.nodes)

    # Find indices of TopSectionTitle nodes that match our target items.
    marker_indices: list[tuple[int, str]] = []  # (index, section_key)

    for idx, node in enumerate(all_nodes):
        if isinstance(node.semantic_element, sp.TopSectionTitle):
            text = node.text.strip()
            m = _ITEM_NUM_RE.search(text)
            if m:
                item_num = m.group(1).lower()
                section_key = _ITEM_KEY_MAP.get(item_num)
                if section_key is not None:
                    marker_indices.append((idx, section_key))

    if not marker_indices:
        return sections

    # For each target marker, collect text from the marker node until the
    # next marker (or end of document).
    for pos, (start_idx, section_key) in enumerate(marker_indices):
        # Determine end boundary
        if pos + 1 < len(marker_indices):
            end_idx = marker_indices[pos + 1][0]
        else:
            end_idx = len(all_nodes)

        parts: list[str] = []
        for node in all_nodes[start_idx:end_idx]:
            node_text = node.text.strip()
            if node_text:
                parts.append(node_text)

        content = "\n\n".join(parts)

        # Skip TOC-length matches
        if len(content) < _MIN_SECTION_LENGTH:
            continue

        # Keep the *longest* match for a given section (handles TOC duplicates).
        if sections[section_key] is None or len(content) > len(sections[section_key]):
            sections[section_key] = content

    return sections


# ---------------------------------------------------------------------------
# Regex fallback approach
# ---------------------------------------------------------------------------

def _parse_with_regex(html_text: str) -> dict[str, str | None]:
    """
    Strip HTML, then use regex patterns to locate section boundaries.
    """
    clean_text = _html_to_text(html_text)
    boundaries = _find_section_boundaries(clean_text)

    sections: dict[str, str | None] = {s: None for s in _TARGET_SECTIONS}
    for key in _TARGET_SECTIONS:
        if key not in boundaries:
            continue
        start, end = boundaries[key]
        content = clean_text[start:end].strip()
        if len(content) >= _MIN_SECTION_LENGTH:
            sections[key] = content

    return sections


def _html_to_text(html: str) -> str:
    """
    Convert HTML to plain text, preserving paragraph structure.

    Tables are converted to readable markdown format before text extraction
    so that financial statement data retains its columnar structure.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove <a> tags that look like TOC links (they typically wrap short
    # text like "Item 1A" inside an anchor).  We keep the surrounding text
    # but remove the anchor itself to avoid false-positive header matches
    # inside the TOC.
    for a_tag in soup.find_all("a"):
        tag_text = a_tag.get_text(strip=True)
        if len(tag_text) < 80 and re.search(r"(?i)item\s+\d+[A-Za-z]?", tag_text):
            a_tag.decompose()

    # Convert HTML tables to markdown before extracting text.
    # This preserves the columnar structure of financial statements.
    for table_tag in soup.find_all("table"):
        markdown = html_table_to_markdown(table_tag)
        if markdown:
            # Replace the table element with its markdown representation
            new_tag = soup.new_tag("div")
            new_tag.append(NavigableString("\n\n" + markdown + "\n\n"))
            table_tag.replace_with(new_tag)
        # If markdown is empty (layout-only table), leave it for get_text()

    text = soup.get_text(separator="\n\n")

    # Collapse runs of 3+ newlines into exactly two.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _find_section_boundaries(text: str) -> dict[str, tuple[int, int]]:
    """
    Find start/end positions of each target section in *text*.

    Algorithm:
    1. For every target section, find *all* regex matches across all its
       patterns.
    2. Collect all matches (section_key, position) and sort by position.
    3. Also find positions of *all* item-like headers (even ones we don't
       extract) so we know where a section ends.
    4. For each target match, the section runs from the match position to
       the start of the *next* item header (of any kind).
    5. Among possibly-duplicate matches for the same section_key, keep
       the one with the longest content (to skip TOC entries).
    """

    # Step 1 — find all matches for our target sections.
    target_matches: list[tuple[str, int]] = []  # (section_key, start_pos)
    for key, patterns in SECTION_PATTERNS.items():
        for pat in patterns:
            for m in re.finditer(pat, text):
                target_matches.append((key, m.start()))

    if not target_matches:
        return {}

    # Step 2 — find *all* item-header positions (including non-target ones
    # like Item 2, Item 9, etc.) so we can determine where each section
    # ends.
    all_header_positions: list[int] = []
    for pat in _ALL_ITEM_PATTERNS:
        for m in pat.finditer(text):
            all_header_positions.append(m.start())

    # Also add "PART" markers as potential boundaries.
    for m in re.finditer(r"(?i)\bPART\s+(?:I{1,3}|IV|V)\b", text):
        all_header_positions.append(m.start())

    all_header_positions = sorted(set(all_header_positions))

    # Step 3 — for each target match, find the end position (start of the
    # *next* header after this one).
    def _next_header_after(pos: int) -> int:
        """Return the position of the next header strictly after *pos*."""
        for hp in all_header_positions:
            if hp > pos:
                return hp
        return len(text)

    # Step 4 — choose a coherent sequence of section boundaries in filing order.
    candidates_by_key: dict[str, list[tuple[int, int]]] = {key: [] for key in _TARGET_SECTIONS}
    for key, start in target_matches:
        end = _next_header_after(start)
        if end - start >= _MIN_SECTION_LENGTH:
            candidates_by_key.setdefault(key, []).append((start, end))

    doc_len = max(len(text), 1)
    boundaries: dict[str, tuple[int, int]] = {}
    prev_start = -1
    target_order = ["item_1", "item_1a", "item_7", "item_7a", "item_8"]
    min_fraction = {
        "item_1": 0.0,
        "item_1a": 0.01,
        "item_7": 0.05,
        "item_7a": 0.08,
        "item_8": 0.10,
    }

    for key in target_order:
        candidates = sorted(candidates_by_key.get(key, []), key=lambda item: item[0])
        if not candidates:
            continue

        viable = [c for c in candidates if c[0] > prev_start + 50]
        if not viable:
            continue

        threshold = int(doc_len * min_fraction.get(key, 0.0))
        preferred = [c for c in viable if c[0] >= threshold]
        pool = preferred or viable

        # Prefer the earliest plausible in-document match to avoid TOC duplicates.
        chosen = min(pool, key=lambda item: item[0])
        boundaries[key] = chosen
        prev_start = chosen[0]

    return boundaries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_enough_sections(sections: dict[str, str | None]) -> bool:
    """Return True if at least 2 sections were successfully extracted."""
    found = sum(1 for v in sections.values() if v is not None)
    return found >= 2
