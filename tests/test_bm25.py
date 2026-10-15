import math

import pytest

from opspilot.triage.bm25 import BM25Index, tokenize

DOCS = [
    "Database connection pool exhausted: raise pool size, check slow queries and leaks",
    "Payment gateway timeout: check upstream gateway status page and retry budget",
    "Disk full on worker nodes: rotate logs and expand the volume",
]


def test_tokenize_lowercases_and_drops_stopwords():
    assert tokenize("The DB-Pool is FULL!") == ["db", "pool", "full"]


def test_relevant_document_ranks_first():
    index = BM25Index(DOCS)
    results = index.search("connection pool exhausted on orders-db")
    assert results[0][0] == 0
    assert results[0][1] > 0


def test_no_overlap_returns_nothing():
    assert BM25Index(DOCS).search("kubernetes certificate expiry") == []


def test_rare_terms_weigh_more_than_common_ones():
    index = BM25Index(["timeout gateway", "timeout disk", "timeout pool"])
    assert index.idf("gateway") > index.idf("timeout")
    assert index.idf("timeout") > 0  # non-negative IDF variant


def test_idf_matches_formula():
    index = BM25Index(DOCS)
    n, df = 3, 1
    assert index.idf("gateway") == pytest.approx(math.log(1 + (n - df + 0.5) / (df + 0.5)))


def test_top_k_limits_results():
    index = BM25Index(DOCS)
    assert len(index.search("check pool gateway logs", top_k=2)) == 2


def test_empty_corpus():
    assert BM25Index([]).search("anything") == []
