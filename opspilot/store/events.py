"""Append-only incident audit trail."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, insert_returning_id
from opspilot.timeutil import to_datetime, utcnow


def record(
    conn: Connection,
    incident_id: int,
    kind: str,
    *,
    actor_id: int | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    detail: dict | None = None,
    at: datetime | None = None,
) -> int:
    return insert_returning_id(
        conn,
        "INSERT INTO incident_events "
        "(incident_id, actor_id, kind, from_status, to_status, detail, created_at) "
        "VALUES (:incident_id, :actor_id, :kind, :from_status, :to_status, :detail, :at)",
        incident_id=incident_id,
        actor_id=actor_id,
        kind=kind,
        from_status=from_status,
        to_status=to_status,
        detail=json.dumps(detail, sort_keys=True) if detail else None,
        at=at or utcnow(),
    )


def for_incident(conn: Connection, incident_id: int) -> list[dict]:
    rows = fetch_all(
        conn,
        """
        SELECT e.id, e.kind, e.from_status, e.to_status, e.detail, e.created_at,
               e.actor_id, eng.name AS actor_name
        FROM incident_events e
        LEFT JOIN engineers eng ON eng.id = e.actor_id
        WHERE e.incident_id = :incident_id
        ORDER BY e.created_at, e.id
        """,
        incident_id=incident_id,
    )
    for row in rows:
        row["created_at"] = to_datetime(row["created_at"])
        row["detail"] = json.loads(row["detail"]) if row["detail"] else None
        row["actor_name"] = row["actor_name"] or "system"
    return rows
