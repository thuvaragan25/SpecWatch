"""Deterministic lexical candidate ranking (BM25).

No embeddings, no vector database -- see plan.md's Requirement Mapping
Strategy and Review Addendum. This is a thin wrapper: tokenize identifiers
(splitting on both snake_case and camelCase boundaries, since symbol
names use both) and rank a small in-memory corpus with BM25.
"""

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    """Split on non-alphanumeric separators and camelCase boundaries."""
    tokens: list[str] = []
    for chunk in _NON_ALNUM_RE.split(text):
        if not chunk:
            continue
        for piece in _CAMEL_BOUNDARY_RE.split(chunk):
            piece = piece.lower().strip()
            if piece:
                tokens.append(piece)
    return tokens


@dataclass(frozen=True)
class Document:
    id: str
    text: str


class BM25Index:
    """A small, in-memory BM25 index over a fixed set of documents."""

    def __init__(self, documents: list[Document]) -> None:
        self._ids = [doc.id for doc in documents]
        corpus_tokens = [tokenize(doc.text) for doc in documents]
        self._bm25 = BM25Okapi(corpus_tokens) if corpus_tokens else None

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Return up to ``limit`` (doc_id, score) pairs with score > 0,
        ranked highest first."""
        if self._bm25 is None:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        ranked = sorted(zip(self._ids, scores), key=lambda pair: pair[1], reverse=True)
        return [(doc_id, float(score)) for doc_id, score in ranked[:limit] if score > 0]
