"""Cross-encoder reranking for passage selection.

Scores (query, passage) pairs with a cross-encoder model for more
accurate relevance scoring than bi-encoder similarity.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


def _preferred_device() -> str | None:
    """Return 'cpu' when FINEDGAR_FORCE_CPU is set, else None (auto-detect)."""
    if os.getenv("FINEDGAR_FORCE_CPU", "0").lower() in {"1", "true", "yes"}:
        return "cpu"
    return None


class CrossEncoderReranker:
    """Rerank passages using a cross-encoder model."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            device = _preferred_device()
            logger.info(
                "Loading cross-encoder: %s%s",
                self.model_name,
                f" (device={device})" if device else "",
            )
            kwargs: dict[str, Any] = {}
            if device:
                kwargs["device"] = device
            self._model = CrossEncoder(self.model_name, **kwargs)
        return self._model

    def rerank(
        self,
        query: str,
        passages: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Score and rerank passages by cross-encoder relevance.

        Args:
            query: The search query
            passages: List of passage dicts (must have "text" key)
            top_k: Number of top passages to return

        Returns:
            Top-k passages sorted by cross-encoder score, with
            "rerank_score" field added.
        """
        if not passages:
            return []

        pairs = [[query, p["text"]] for p in passages]
        scores = self.model.predict(pairs)

        for passage, score in zip(passages, scores):
            passage["rerank_score"] = float(score)

        ranked = sorted(passages, key=lambda p: p["rerank_score"], reverse=True)
        return ranked[:top_k]


# Module-level singleton
_reranker: CrossEncoderReranker | None = None


def get_reranker() -> CrossEncoderReranker:
    """Get the shared CrossEncoderReranker instance."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker()
    return _reranker
