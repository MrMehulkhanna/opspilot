"""Generate and review AI triage suggestions.

incident -> BM25 runbook retrieval -> LLM (if configured) -> validate
                                   \\-> rule-based fallback on any failure
suggestion (pending) -> engineer approves / edits / rejects -> audited
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import Connection

from opspilot import incidents
from opspilot.errors import Conflict, NotFound, ValidationError
from opspilot.store import engineers, events, runbooks, suggestions
from opspilot.triage.llm import SYSTEM_PROMPT, LLMClient, LLMError, build_prompt, parse_suggestion
from opspilot.triage.retriever import retrieve
from opspilot.triage.rules import rule_based_suggestion

log = logging.getLogger(__name__)


def suggest(
    conn: Connection, incident_id: int, llm: LLMClient | None = None, top_k: int = 3
) -> dict:
    incident = incidents.get_or_404(conn, incident_id)
    if incident["status"] == "closed":
        raise Conflict("closed incidents cannot be triaged")

    retrieved = retrieve(runbooks.list_all(conn), incident, top_k=top_k)

    source, model, result, fallback_reason = "rules", None, None, None
    if llm is not None:
        try:
            raw = llm.complete(SYSTEM_PROMPT, build_prompt(incident, retrieved))
            result = parse_suggestion(raw)
            source, model = "llm", llm.model
        except LLMError as exc:
            fallback_reason = str(exc)
            log.warning("LLM triage failed for incident %s: %s", incident_id, exc)
    else:
        fallback_reason = "no LLM configured"
    if result is None:
        result = rule_based_suggestion(incident, retrieved)

    suggestion_id = suggestions.insert(
        conn,
        incident_id=incident_id,
        source=source,
        model=model,
        probable_cause=result["probable_cause"],
        steps=result["steps"],
        severity=result["severity"],
        runbooks=retrieved,
    )
    detail = {
        "suggestion_id": suggestion_id,
        "source": source,
        "runbooks": [r.slug for r in retrieved],
    }
    if fallback_reason:
        detail["fallback_reason"] = fallback_reason
    events.record(conn, incident_id, "ai_suggested", detail=detail)
    return suggestions.get(conn, suggestion_id)


REVIEW_DECISIONS = ("approve", "edit", "reject")


def review(
    conn: Connection,
    suggestion_id: int,
    *,
    decision: str,
    reviewer_id: int,
    edited_steps: list[str] | None = None,
    comment: str | None = None,
) -> dict:
    """Human-in-the-loop: nothing an AI suggests is used until an engineer decides."""
    if decision not in REVIEW_DECISIONS:
        raise ValidationError(f"decision must be one of {', '.join(REVIEW_DECISIONS)}")
    suggestion = suggestions.get(conn, suggestion_id)
    if suggestion is None:
        raise NotFound(f"suggestion {suggestion_id} not found")
    if suggestion["status"] != "pending":
        raise Conflict(f"suggestion {suggestion_id} was already {suggestion['status']}")
    if engineers.get(conn, reviewer_id) is None:
        raise NotFound(f"engineer {reviewer_id} not found")

    if decision == "approve":
        status, final = "approved", suggestion["suggested_steps"]
    elif decision == "edit":
        cleaned = [s.strip() for s in (edited_steps or []) if s and s.strip()]
        if not cleaned:
            raise ValidationError("an edit must include at least one step")
        status, final = "edited", cleaned
    else:
        if not (comment and comment.strip()):
            raise ValidationError("say why the suggestion is rejected")
        status, final = "rejected", None

    suggestions.mark_reviewed(
        conn,
        suggestion_id,
        status=status,
        reviewer_id=reviewer_id,
        final_steps=final,
        comment=comment.strip() if comment else None,
    )
    events.record(
        conn,
        suggestion["incident_id"],
        f"ai_{status}",
        actor_id=reviewer_id,
        detail={"suggestion_id": suggestion_id, "comment": comment}
        if comment
        else {"suggestion_id": suggestion_id},
    )
    return suggestions.get(conn, suggestion_id)
