#!/usr/bin/env python3
"""Build FAISS vector index from all filing chunks.

Usage:
    python scripts/build_vector_index.py
    python scripts/build_vector_index.py --model BAAI/bge-small-en-v1.5
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.data.embeddings import EmbeddingIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(description="Build FAISS vector index")
    parser.add_argument(
        "--model",
        default="BAAI/bge-small-en-v1.5",
        help="Sentence-transformer model name",
    )
    args = parser.parse_args()

    start = time.time()

    idx = EmbeddingIndex(model_name=args.model)
    idx.build_index()
    idx.save()

    elapsed = time.time() - start
    print(f"\nDone. {idx.index.ntotal} vectors indexed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
