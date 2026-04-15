"""
Phase B self-bootstrap: generate diff summaries using base Gemma 4 E4B via Ollama.

Reads pairs of section texts from consecutive years, sends them to the local
Ollama instance with a summarization prompt, and saves raw outputs to
data/training/diff_review_queue.jsonl for manual review and curation.

Usage:
    python model/training/bootstrap_diffs.py
    python model/training/bootstrap_diffs.py --limit 80
    python model/training/bootstrap_diffs.py --model gemma4:e4b

Requires:
    - Ollama running at http://localhost:11434 with gemma4:e4b loaded
    - Parsed section data at data/parsed/{ticker}/{year}/sections.json
"""

import argparse
import json
import os
import random
import sys
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARSED_DIR = PROJECT_ROOT / "data" / "parsed"
OUTPUT_PATH = PROJECT_ROOT / "data" / "training" / "diff_review_queue.jsonl"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = "gemma4:e4b"
REQUEST_TIMEOUT = 120.0  # seconds


def ollama_generate_url() -> str:
    return f"{os.getenv('OLLAMA_HOST', OLLAMA_HOST).rstrip('/')}/api/generate"

_SECTION_FRIENDLY_NAMES = {
    "item_1": "Business",
    "item_1a": "Risk Factors",
    "item_7": "Management's Discussion and Analysis",
    "item_7a": "Quantitative and Qualitative Disclosures About Market Risk",
    "item_8": "Financial Statements and Supplementary Data",
}

# Summarization prompt sent to Ollama
SUMMARIZE_PROMPT_TEMPLATE = """\
You are a financial analyst comparing two versions of a company's SEC 10-K filing.

Company: {company}
Section: {section_name}
Year 1 (FY{y1}):
---
{text_y1_excerpt}
---

Year 2 (FY{y2}):
---
{text_y2_excerpt}
---

Please provide a concise summary (3-5 sentences) of the key differences between these two versions of the {section_name} section. Focus on:
1. What substantive content was added or removed
2. Any changes in tone, risk emphasis, or strategic direction
3. Notable numerical changes if any

Summary of key differences:"""


def _truncate(text: str, max_chars: int = 3000) -> str:
    """Truncate text to fit within prompt limits."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def _load_companies() -> dict[str, str]:
    """Load ticker -> company name mapping."""
    path = PROJECT_ROOT / "data" / "companies.json"
    with open(path, "r", encoding="utf-8") as f:
        companies = json.load(f)
    return {c["ticker"]: c["name"] for c in companies}


def _collect_section_pairs() -> list[dict]:
    """Collect all consecutive-year section pairs from parsed data."""
    ticker_to_name = _load_companies()
    pairs = []

    if not PARSED_DIR.exists():
        print("No parsed data directory found.")
        return pairs

    for ticker_dir in sorted(PARSED_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name
        company_name = ticker_to_name.get(ticker, ticker)

        year_dirs = sorted(
            [d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()],
            key=lambda d: int(d.name),
        )

        if len(year_dirs) < 2:
            continue

        for idx in range(len(year_dirs) - 1):
            y1_dir = year_dirs[idx]
            y2_dir = year_dirs[idx + 1]
            y1 = int(y1_dir.name)
            y2 = int(y2_dir.name)

            s1_path = y1_dir / "sections.json"
            s2_path = y2_dir / "sections.json"
            if not s1_path.exists() or not s2_path.exists():
                continue

            with open(s1_path, "r", encoding="utf-8") as f:
                sections_y1 = json.load(f)
            with open(s2_path, "r", encoding="utf-8") as f:
                sections_y2 = json.load(f)

            for section_key, section_name in _SECTION_FRIENDLY_NAMES.items():
                text_y1 = sections_y1.get(section_key)
                text_y2 = sections_y2.get(section_key)
                if not text_y1 or not text_y2:
                    continue

                # Skip very short sections
                if len(text_y1) < 200 or len(text_y2) < 200:
                    continue

                pairs.append({
                    "ticker": ticker,
                    "company": company_name,
                    "section_key": section_key,
                    "section_name": section_name,
                    "y1": y1,
                    "y2": y2,
                    "text_y1": text_y1,
                    "text_y2": text_y2,
                })

    return pairs


def _call_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str | None:
    """Send a prompt to local Ollama and return the response text."""
    try:
        response = httpx.post(
            ollama_generate_url(),
            json={
                "model": model,
                "prompt": prompt,
                "options": {"temperature": 0.3, "num_predict": 512},
                "stream": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("response", "")
    except httpx.ConnectError:
        print("ERROR: Cannot connect to Ollama at", ollama_generate_url())
        print("Make sure Ollama is running: ollama serve")
        return None
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Ollama returned HTTP {e.response.status_code}")
        return None
    except httpx.TimeoutException:
        print("WARNING: Ollama request timed out after", REQUEST_TIMEOUT, "seconds")
        return None


def bootstrap_diffs(model: str = DEFAULT_MODEL, limit: int = 80) -> None:
    """Generate diff summaries via Ollama and save to review queue.

    Args:
        model: Ollama model name to use.
        limit: Maximum number of pairs to process (target 50-80).
    """
    print(f"Collecting section pairs from {PARSED_DIR}...")
    all_pairs = _collect_section_pairs()
    print(f"Found {len(all_pairs)} section pairs across all companies.")

    if not all_pairs:
        print("No section pairs found. Ensure parsed data exists.")
        return

    # Shuffle and limit
    rng = random.Random(42)
    rng.shuffle(all_pairs)
    pairs = all_pairs[:limit]
    print(f"Processing {len(pairs)} pairs (limit={limit})...")

    # Ensure output directory exists
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for i, pair in enumerate(pairs, 1):
        prompt = SUMMARIZE_PROMPT_TEMPLATE.format(
            company=pair["company"],
            section_name=pair["section_name"],
            y1=pair["y1"],
            y2=pair["y2"],
            text_y1_excerpt=_truncate(pair["text_y1"]),
            text_y2_excerpt=_truncate(pair["text_y2"]),
        )

        print(f"  [{i}/{len(pairs)}] {pair['ticker']} {pair['section_name']} "
              f"FY{pair['y1']}->FY{pair['y2']}...", end=" ", flush=True)

        summary = _call_ollama(prompt, model=model)

        if summary is None:
            print("FAILED")
            if i == 1:
                print("First request failed — aborting. Is Ollama running?")
                break
            continue

        print("OK")

        # Build the question that this would answer
        question = (
            f"How did {pair['company']}'s {pair['section_name']} section change "
            f"between their FY{pair['y1']} and FY{pair['y2']} 10-K filings?"
        )

        results.append({
            "messages": [
                {"role": "user", "content": question},
                {"role": "assistant", "content": summary.strip()},
            ],
            "_meta": {
                "ticker": pair["ticker"],
                "section": pair["section_key"],
                "y1": pair["y1"],
                "y2": pair["y2"],
                "model": model,
                "status": "review",  # manual review needed
            },
        })

    # Write results
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(results)} raw pairs to {OUTPUT_PATH}")
    print("Next steps:")
    print("  1. Review each entry in the file")
    print("  2. Remove or fix low-quality summaries")
    print("  3. Remove the '_meta' field from approved entries")
    print("  4. Move curated entries to data/training/diff_summaries_bootstrap.jsonl")


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap diff summaries using base Gemma 4 E4B via Ollama."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=80,
        help="Maximum number of section pairs to process (default: 80)",
    )
    args = parser.parse_args()

    bootstrap_diffs(model=args.model, limit=args.limit)


if __name__ == "__main__":
    main()
