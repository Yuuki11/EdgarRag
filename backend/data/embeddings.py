"""Dense retrieval using sentence-transformers + FAISS.

Provides embedding-based search over filing chunks, with metadata
filtering for ticker, year, and section.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

INDEX_DIR = Path("data/vector_index")
CHUNKS_DIR = Path("data/chunks")


def _preferred_device() -> str | None:
    """Return 'cpu' when FINEDGAR_FORCE_CPU is set, else None (auto-detect)."""
    if os.getenv("FINEDGAR_FORCE_CPU", "0").lower() in {"1", "true", "yes"}:
        return "cpu"
    return None


def _infer_document_id(chunks_path: Path, year: int) -> str:
    if chunks_path.parent.name == str(year):
        return f"10-K_{year}"
    return chunks_path.parent.name


def _infer_doc_type(chunk: dict, chunks_path: Path) -> str:
    form_type = str(chunk.get("form_type", "")).upper()
    if form_type:
        return form_type
    doc_name = chunks_path.parent.name.upper()
    for token in ("10-K", "10-Q", "8-K", "DEF 14A", "EX-99", "EARNINGS"):
        if token in doc_name:
            return token
    return "UNKNOWN"


def _infer_fiscal_period(chunk: dict) -> str:
    text = str(chunk.get("text", ""))[:200].lower()
    if "three months ended" in text or "first quarter" in text or "q1" in text:
        return "Q1"
    if "six months ended" in text or "second quarter" in text or "q2" in text:
        return "Q2"
    if "nine months ended" in text or "third quarter" in text or "q3" in text:
        return "Q3"
    if str(chunk.get("form_type", "")).upper() == "10-Q":
        return "Q?"
    return "FY"


def _section_family(section: str, section_name: str) -> str:
    section_name_lower = section_name.lower()
    if section == "item_8" or "financial statement" in section_name_lower:
        return "financials"
    if section == "item_7" or "management" in section_name_lower:
        return "mda"
    if section == "item_1a":
        return "risk"
    if section == "item_1":
        return "business"
    return "other"


def _normalize_chunk_record(chunk: dict, chunks_path: Path, year: int) -> dict:
    return {
        **chunk,
        "document_id": chunk.get("document_id") or _infer_document_id(chunks_path, year),
        "doc_type": chunk.get("doc_type") or _infer_doc_type(chunk, chunks_path),
        "doc_name": chunk.get("doc_name") or (chunk.get("document_id") or _infer_document_id(chunks_path, year)),
        "fiscal_period": chunk.get("fiscal_period") or _infer_fiscal_period(chunk),
        "section_family": chunk.get("section_family") or _section_family(str(chunk.get("section", "")), str(chunk.get("section_name", ""))),
    }


def _normalize_index_metadata(meta: dict) -> dict:
    doc_name = meta.get("doc_name") or meta.get("document_id", "")
    section = str(meta.get("section", ""))
    section_name = str(meta.get("section_name", ""))
    normalized = {
        **meta,
        "doc_type": meta.get("doc_type") or str(meta.get("form_type", "")).upper() or "UNKNOWN",
        "doc_name": doc_name,
        "fiscal_period": meta.get("fiscal_period") or "FY",
        "section_family": meta.get("section_family") or _section_family(section, section_name),
    }
    return normalized


class EmbeddingIndex:
    """FAISS-backed dense retrieval index over filing chunks."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model: SentenceTransformer | None = None
        self.index: faiss.IndexFlatIP | None = None
        self.metadata: list[dict] = []  # parallel to FAISS vectors
        self._dimension: int = 0

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            device = _preferred_device()
            logger.info(
                "Loading embedding model: %s%s",
                self.model_name,
                f" (device={device})" if device else "",
            )
            kwargs: dict[str, Any] = {}
            if device:
                kwargs["device"] = device
            self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model

    def _embed(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        """Embed texts and L2-normalize for cosine similarity via inner product."""
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 100,
            normalize_embeddings=True,  # L2 normalize for cosine sim
        )
        return np.asarray(embeddings, dtype=np.float32)

    def build_index(self, chunks_dir: Path | None = None) -> None:
        """Load all chunks, embed them, and build a FAISS flat index."""
        chunks_dir = chunks_dir or CHUNKS_DIR
        if not chunks_dir.exists():
            raise FileNotFoundError(f"Chunks directory not found: {chunks_dir}")

        # Collect all chunks
        all_chunks: list[dict] = []
        for ticker_dir in sorted(chunks_dir.iterdir()):
            if not ticker_dir.is_dir():
                continue
            for year_dir in sorted(ticker_dir.iterdir()):
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue
                chunk_files = []
                direct = year_dir / "chunks.json"
                if direct.exists():
                    chunk_files.append(direct)
                chunk_files.extend(sorted(year_dir.rglob("chunks.json")))
                seen_paths: set[Path] = set()
                for chunks_path in chunk_files:
                    if chunks_path in seen_paths:
                        continue
                    seen_paths.add(chunks_path)
                    with open(chunks_path) as f:
                        raw_chunks = json.load(f)
                    chunks = [_normalize_chunk_record(chunk, chunks_path, int(year_dir.name)) for chunk in raw_chunks]
                    all_chunks.extend(chunks)

        if not all_chunks:
            raise ValueError("No chunks found to index")

        logger.info("Embedding %d chunks...", len(all_chunks))

        # Extract texts for embedding
        texts = [chunk["text"] for chunk in all_chunks]

        # Embed in batches
        embeddings = self._embed(texts)
        self._dimension = embeddings.shape[1]

        # Build FAISS index (flat inner product = cosine similarity on normalized vectors)
        self.index = faiss.IndexFlatIP(self._dimension)
        self.index.add(embeddings)

        # Store metadata parallel to index
        self.metadata = [
            {
                "ticker": chunk.get("ticker", ""),
                "year": chunk.get("year", 0),
                "document_id": chunk.get("document_id", ""),
                "section": chunk.get("section", ""),
                "section_name": chunk.get("section_name", ""),
                "chunk_index": chunk.get("chunk_index", 0),
                "chunk_type": chunk.get("chunk_type", "text"),
                "filing_date": chunk.get("filing_date", ""),
                "form_type": chunk.get("form_type", ""),
                "source_url": chunk.get("source_url", ""),
                "token_count": chunk.get("token_count", 0),
                "doc_type": chunk.get("doc_type", ""),
                "doc_name": chunk.get("doc_name", ""),
                "fiscal_period": chunk.get("fiscal_period", ""),
                "section_family": chunk.get("section_family", ""),
                "text": chunk["text"],
            }
            for chunk in all_chunks
        ]

        logger.info(
            "Built FAISS index: %d vectors, %d dimensions",
            self.index.ntotal,
            self._dimension,
        )

    def search(
        self,
        query: str,
        ticker: str | None = None,
        year: int | None = None,
        sections: list[str] | None = None,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Search the index for chunks similar to query.

        Metadata filtering is applied post-hoc (FAISS doesn't support
        pre-filtering natively with flat index). We over-retrieve and
        then filter.
        """
        if self.index is None or not self.metadata:
            return []

        # Over-retrieve to compensate for post-hoc filtering
        fetch_k = min(top_k * 5, self.index.ntotal)

        query_embedding = self._embed([query])
        scores, indices = self.index.search(query_embedding, fetch_k)

        results: list[dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:  # FAISS returns -1 for missing results
                continue
            meta = self.metadata[idx]

            # Apply metadata filters
            if ticker and meta["ticker"].upper() != ticker.upper():
                continue
            if year and meta["year"] != year:
                continue
            if sections and meta["section"] not in sections:
                continue

            results.append({**meta, "dense_score": float(score)})

            if len(results) >= top_k:
                break

        return results

    def save(self, path: Path | None = None) -> None:
        """Persist the FAISS index and metadata to disk."""
        path = path or INDEX_DIR
        path.mkdir(parents=True, exist_ok=True)

        if self.index is None:
            raise ValueError("No index to save — call build_index() first")

        faiss.write_index(self.index, str(path / "index.faiss"))
        with open(path / "metadata.pkl", "wb") as f:
            pickle.dump(
                {"metadata": self.metadata, "dimension": self._dimension, "model_name": self.model_name},
                f,
            )
        logger.info("Saved index to %s (%d vectors)", path, self.index.ntotal)

    def load(self, path: Path | None = None) -> None:
        """Load a previously saved FAISS index and metadata."""
        path = path or INDEX_DIR

        index_path = path / "index.faiss"
        meta_path = path / "metadata.pkl"

        if not index_path.exists() or not meta_path.exists():
            raise FileNotFoundError(f"No saved index found at {path}")

        self.index = faiss.read_index(str(index_path))
        with open(meta_path, "rb") as f:
            data = pickle.load(f)
        self.metadata = [_normalize_index_metadata(meta) for meta in data["metadata"]]
        self._dimension = data["dimension"]
        self.model_name = data.get("model_name", self.model_name)

        logger.info(
            "Loaded FAISS index: %d vectors, %d dimensions",
            self.index.ntotal,
            self._dimension,
        )


# Module-level singleton for lazy loading
_index: EmbeddingIndex | None = None


def get_index() -> EmbeddingIndex | None:
    """Get the shared EmbeddingIndex, loading from disk if available."""
    global _index
    if _index is not None:
        return _index

    idx = EmbeddingIndex()
    try:
        idx.load()
        _index = idx
        return _index
    except FileNotFoundError:
        return None
