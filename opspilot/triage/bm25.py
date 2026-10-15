"""Okapi BM25 ranking, implemented from the formula.

score(D, Q) = sum over q in Q of
    IDF(q) * f(q, D) * (k1 + 1) / (f(q, D) + k1 * (1 - b + b * |D| / avgdl))

IDF uses the non-negative variant ln(1 + (N - n(q) + 0.5) / (n(q) + 0.5)) so
very common terms never subtract from a score.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "when",
        "then",
        "if",
        "not",
        "no",
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


class BM25Index:
    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs = [Counter(tokenize(doc)) for doc in documents]
        self._lengths = [sum(tf.values()) for tf in self._docs]
        self.n_docs = len(self._docs)
        self.avgdl = (sum(self._lengths) / self.n_docs) if self.n_docs else 0.0
        df: Counter = Counter()
        for tf in self._docs:
            df.update(tf.keys())
        self._idf = {
            term: math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5)) for term, n in df.items()
        }

    def idf(self, term: str) -> float:
        return self._idf.get(term, 0.0)

    def score(self, query: str, index: int) -> float:
        tf = self._docs[index]
        length = self._lengths[index]
        norm = self.k1 * (1 - self.b + self.b * length / self.avgdl) if self.avgdl else self.k1
        total = 0.0
        for term in tokenize(query):
            freq = tf.get(term, 0)
            if freq:
                total += self.idf(term) * freq * (self.k1 + 1) / (freq + norm)
        return total

    def search(self, query: str, top_k: int = 3) -> list[tuple[int, float]]:
        """Return up to top_k (doc_index, score) pairs with score > 0, best first."""
        scored = [(i, self.score(query, i)) for i in range(self.n_docs)]
        scored = [pair for pair in scored if pair[1] > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top_k]
