from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, fetch_one, insert_returning_id
from opspilot.timeutil import to_datetime, utcnow


def _normalize(row: dict | None) -> dict | None:
    if row is None:
        return None
    row["suggested_steps"] = json.loads(row["suggested_steps"])
    row["final_steps"] = json.loads(row["final_steps"]) if row["final_steps"] else None
    row["created_at"] = to_datetime(row["created_at"])
    row["reviewed_at"] = to_datetime(row["reviewed_at"])
    return row


def insert(
    conn: Connection,
    *,
    incident_id: int,
    source: str,
    model: str | None,
    probable_cause: str,
    steps: list[str],
    severity: str | None,
    runbooks: list,
) -> int:
    suggestion_id = insert_returning_id(
        conn,
        """
        INSERT INTO ai_suggestions (incident_id, source, model, probable_cause,
                                    suggested_steps, suggested_severity, status, created_at)
        VALUES (:incident_id, :source, :model, :cause, :steps, :severity, 'pending', :now)
        """,
        incident_id=incident_id,
        source=source,
        model=model,
        cause=probable_cause,
        steps=json.dumps(steps),
        severity=severity,
        now=utcnow(),
    )
    for rb in runbooks:
        conn.execute(
            text(
                "INSERT INTO suggestion_runbooks (suggestion_id, runbook_id, rank, score)"
                " VALUES (:sid, :rid, :rank, :score)"
            ),
            {"sid": suggestion_id, "rid": rb.id, "rank": rb.rank, "score": rb.score},
        )
    return suggestion_id


def get(conn: Connection, suggestion_id: int) -> dict | None:
    row = _normalize(
        fetch_one(conn, "SELECT * FROM ai_suggestions WHERE id = :id", id=suggestion_id)
    )
    if row:
        row["runbooks"] = runbooks_for(conn, suggestion_id)
    return row


def runbooks_for(conn: Connection, suggestion_id: int) -> list[dict]:
    return fetch_all(
        conn,
        """
        SELECT r.id, r.slug, r.title, sr.rank, sr.score
        FROM suggestion_runbooks sr
        JOIN runbooks r ON r.id = sr.runbook_id
        WHERE sr.suggestion_id = :sid
        ORDER BY sr.rank
        """,
        sid=suggestion_id,
    )


def for_incident(conn: Connection, incident_id: int) -> list[dict]:
    rows = fetch_all(
        conn,
        "SELECT * FROM ai_suggestions WHERE incident_id = :iid ORDER BY created_at DESC, id DESC",
        iid=incident_id,
    )
    result = []
    for row in rows:
        row = _normalize(row)
        row["runbooks"] = runbooks_for(conn, row["id"])
        result.append(row)
    return result


def mark_reviewed(
    conn: Connection,
    suggestion_id: int,
    *,
    status: str,
    reviewer_id: int,
    final_steps: list[str] | None,
    comment: str | None,
) -> None:
    conn.execute(
        text(
            "UPDATE ai_suggestions SET status = :status, reviewed_by = :reviewer,"
            " reviewed_at = :now, final_steps = :final, review_comment = :comment"
            " WHERE id = :id AND status = 'pending'"
        ),
        {
            "status": status,
            "reviewer": reviewer_id,
            "now": utcnow(),
            "final": json.dumps(final_steps) if final_steps is not None else None,
            "comment": comment,
            "id": suggestion_id,
        },
    )
