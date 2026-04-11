"""Section-aware chunking for 10-K filing sections.

Splits parsed section text into retrieval-friendly chunks with full metadata,
using tiktoken (cl100k_base) for accurate token counting.
"""

from __future__ import annotations

import re

import tiktoken

from backend.data.models import FilingChunk

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_encoding = tiktoken.get_encoding("cl100k_base")


def _token_count(text: str) -> int:
    """Return the number of tokens in *text* using cl100k_base."""
    return len(_encoding.encode(text))


def _encode(text: str) -> list[int]:
    return _encoding.encode(text)


def _decode(tokens: list[int]) -> str:
    return _encoding.decode(tokens)


# ---------------------------------------------------------------------------
# Sentence splitting helper
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TABLE_LINE_RE = re.compile(r"^.+\|.+$", re.MULTILINE)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (simple heuristic)."""
    parts = _SENTENCE_RE.split(text)
    return [p for p in parts if p.strip()]


def _is_table_block(text: str) -> bool:
    """Check if a text block contains a markdown table."""
    lines = text.strip().split("\n")
    pipe_lines = sum(1 for l in lines if "|" in l)
    return pipe_lines >= 2


def _split_table_by_rows(
    table_text: str, chunk_size: int
) -> list[tuple[str, bool]]:
    """Split a large markdown table at row boundaries, repeating the header.

    Returns list of (chunk_text, is_table) tuples.
    """
    lines = table_text.strip().split("\n")

    # Identify header: first line(s) + separator line (---)
    header_lines: list[str] = []
    data_lines: list[str] = []
    header_done = False

    for line in lines:
        if not header_done:
            header_lines.append(line)
            if "---" in line:
                header_done = True
        else:
            data_lines.append(line)

    # If no separator found, treat first line as header
    if not header_done and lines:
        header_lines = [lines[0]]
        data_lines = lines[1:]

    header_text = "\n".join(header_lines)
    header_tokens = _token_count(header_text)

    if header_tokens >= chunk_size:
        # Header alone exceeds chunk_size — just return as-is
        return [(table_text, True)]

    # Group data lines into chunks, each prefixed with header
    chunks: list[tuple[str, bool]] = []
    current_lines: list[str] = []
    current_tokens = header_tokens

    for line in data_lines:
        line_tokens = _token_count(line)
        if current_tokens + line_tokens > chunk_size and current_lines:
            chunk = header_text + "\n" + "\n".join(current_lines)
            chunks.append((chunk, True))
            current_lines = []
            current_tokens = header_tokens
        current_lines.append(line)
        current_tokens += line_tokens

    if current_lines:
        chunk = header_text + "\n" + "\n".join(current_lines)
        chunks.append((chunk, True))

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_section(
    text: str,
    ticker: str,
    year: int,
    document_id: str,
    section: str,
    section_name: str,
    filing_date: str,
    source_url: str,
    form_type: str = "10-K",
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[FilingChunk]:
    """Split a section into chunks with full metadata.

    Algorithm
    ---------
    1. Split *text* into blocks (paragraphs and tables).
    2. Tables are kept intact when possible; split at row boundaries if needed.
    3. Non-table text is grouped greedily up to *chunk_size* tokens.
    4. Add overlap from previous chunk's last *chunk_overlap* tokens (text only).

    Chunks shorter than 100 tokens are discarded (headers / boilerplate).
    No chunk will exceed *chunk_size* tokens (hard limit).
    """
    if not text or not text.strip():
        return []

    # Split into paragraphs, preserving table blocks
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    # Separate tables from text: group consecutive pipe-containing lines
    # back into table blocks
    blocks: list[tuple[str, bool]] = []  # (text, is_table)
    current_table_lines: list[str] = []

    for para in paragraphs:
        if _is_table_block(para):
            current_table_lines.append(para)
        else:
            # Flush any pending table
            if current_table_lines:
                blocks.append(("\n".join(current_table_lines), True))
                current_table_lines = []
            blocks.append((para, False))

    if current_table_lines:
        blocks.append(("\n".join(current_table_lines), True))

    # Process blocks into sized pieces
    pieces: list[tuple[str, bool]] = []  # (text, is_table)
    for block_text, is_table in blocks:
        if is_table:
            tc = _token_count(block_text)
            if tc <= chunk_size:
                pieces.append((block_text, True))
            else:
                # Split table at row boundaries
                pieces.extend(_split_table_by_rows(block_text, chunk_size))
        else:
            tc = _token_count(block_text)
            if tc <= chunk_size:
                pieces.append((block_text, False))
            else:
                sentences = _split_sentences(block_text)
                for sent in sentences:
                    if _token_count(sent) <= chunk_size:
                        pieces.append((sent, False))
                    else:
                        tokens = _encode(sent)
                        for i in range(0, len(tokens), chunk_size):
                            pieces.append((_decode(tokens[i : i + chunk_size]), False))

    # Greedy grouping: tables become their own chunks, text is grouped
    raw_chunks: list[tuple[str, bool]] = []  # (text, is_table)
    current_parts: list[str] = []
    current_tokens = 0
    current_is_table = False

    for piece_text, is_table in pieces:
        piece_tokens = _token_count(piece_text)

        if is_table:
            # Flush any pending text chunk
            if current_parts:
                raw_chunks.append(("\n\n".join(current_parts), False))
                current_parts = []
                current_tokens = 0
            # Table gets its own chunk
            raw_chunks.append((piece_text, True))
        else:
            if current_tokens + piece_tokens > chunk_size and current_parts:
                raw_chunks.append(("\n\n".join(current_parts), False))
                current_parts = []
                current_tokens = 0
            current_parts.append(piece_text)
            current_tokens += piece_tokens

    if current_parts:
        raw_chunks.append(("\n\n".join(current_parts), False))

    # Apply overlap for text chunks only (not tables)
    final_chunks: list[tuple[str, bool]] = []
    for i, (chunk_text, is_table) in enumerate(raw_chunks):
        if i > 0 and chunk_overlap > 0 and not is_table:
            prev_text, prev_is_table = raw_chunks[i - 1]
            if not prev_is_table:
                prev_tokens = _encode(prev_text)
                overlap_tokens = prev_tokens[-chunk_overlap:]
                overlap_text = _decode(overlap_tokens).strip()
                combined = overlap_text + "\n\n" + chunk_text
                combined_tokens = _encode(combined)
                if len(combined_tokens) > chunk_size:
                    combined = _decode(combined_tokens[:chunk_size])
                final_chunks.append((combined, False))
                continue
        final_chunks.append((chunk_text, is_table))

    # Build FilingChunk objects, filtering out short chunks.
    min_tokens = 100
    chunks: list[FilingChunk] = []
    chunk_index = 0

    for text_block, is_table in final_chunks:
        tc = _token_count(text_block)
        if tc < min_tokens:
            continue
        chunks.append(
            FilingChunk(
                text=text_block,
                ticker=ticker,
                year=year,
                document_id=document_id,
                section=section,
                section_name=section_name,
                chunk_index=chunk_index,
                filing_date=filing_date,
                form_type=form_type,
                source_url=source_url,
                token_count=tc,
                chunk_type="table" if is_table else "text",
            )
        )
        chunk_index += 1

    return chunks
