"""Retrieve the runbooks most relevant to an incident (the 'R' in RAG)."""

from __future__ import annotations

from dataclasses import dataclass

from opspilot.triage.bm25 import BM25Index


@dataclass(frozen=True)
class RetrievedRunbook:
    id: int
    slug: str
    title: str
    body: str
    score: float
    rank: int


def incident_query(incident: dict) -> str:
    parts = [incident.get("service_name") or "", incident.get("title") or ""]
    if incident.get("sample_message"):
        parts.append(incident["sample_message"])
    return " ".join(parts)


def retrieve(runbooks: list[dict], incident: dict, top_k: int = 3) -> list[RetrievedRunbook]:
    if not runbooks:
        return []
    corpus = [f"{rb['title']} {rb.get('service_tag') or ''} {rb['body']}" for rb in runbooks]
    index = BM25Index(corpus)
    hits = index.search(incident_query(incident), top_k=top_k)
    return [
        RetrievedRunbook(
            id=runbooks[i]["id"],
            slug=runbooks[i]["slug"],
            title=runbooks[i]["title"],
            body=runbooks[i]["body"],
            score=round(score, 4),
            rank=rank,
        )
        for rank, (i, score) in enumerate(hits, start=1)
    ]
