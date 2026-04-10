"""Generic document extraction for HTML, PDF, and plain text filings."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString

from .table_extractor import html_table_to_markdown

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_html_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    for table_tag in soup.find_all("table"):
        markdown = html_table_to_markdown(table_tag)
        if markdown:
            new_tag = soup.new_tag("div")
            new_tag.append(NavigableString("\n\n" + markdown + "\n\n"))
            table_tag.replace_with(new_tag)

    text = soup.get_text(separator="\n\n")
    return _normalize_text(text)


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf is not installed; cannot extract PDF text from %s", path)
        return ""

    try:
        reader = PdfReader(str(path))
    except Exception:
        logger.exception("Failed to open PDF document %s", path)
        return ""

    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            logger.warning("Failed to extract page %d from %s", index, path)
            page_text = ""
        page_text = _normalize_text(page_text)
        if page_text:
            pages.append(f"[Page {index}]\n{page_text}")
    return "\n\n".join(pages)


def extract_document_text(filepath: str) -> str:
    """Extract normalized text from an HTML, PDF, or plain-text document."""
    path = Path(filepath)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf_text(path)

    raw_bytes = path.read_bytes()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = raw_bytes.decode("latin-1", errors="replace")

    if suffix in {".html", ".htm", ".xhtml"} or "<html" in raw_text.lower():
        return _extract_html_text(raw_text)

    return _normalize_text(raw_text)


def parse_generic_document(filepath: str) -> dict[str, str | None]:
    """Parse a non-10-K document into a retrieval-ready single text section."""
    text = extract_document_text(filepath)
    if not text:
        return {"full_document": None}
    return {"full_document": text}
