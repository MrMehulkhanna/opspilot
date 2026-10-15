from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, fetch_one, insert_returning_id
from opspilot.timeutil import to_datetime

_TS_COLUMNS = (
    "opened_at",
    "acknowledged_at",
    "resolved_at",
    "closed_at",
    "ack_due_at",
    "resolve_due_at",
)

_SELECT = """
    SELECT i.*, s.name AS service_name, s.team AS service_team,
           eng.name AS assignee_name
    FROM incidents i
    JOIN services s ON s.id = i.service_id
    LEFT JOIN engineers eng ON eng.id = i.assignee_id
"""


def _normalize(row: dict | None) -> dict | None:
    if row is None:
        return None
    for col in _TS_COLUMNS:
        row[col] = to_datetime(row.get(col))
    return row


def insert(
    conn: Connection,
    *,
    service_id: int,
    title: str,
    severity: str,
    opened_at: datetime,
    ack_due_at: datetime,
    resolve_due_at: datetime,
    error_count: int = 0,
    sample_message: str | None = None,
) -> int:
    return insert_returning_id(
        conn,
        """
        INSERT INTO incidents (service_id, title, severity, status, error_count,
                               sample_message, opened_at, ack_due_at, resolve_due_at)
        VALUES (:service_id, :title, :severity, 'open', :error_count,
                :sample_message, :opened_at, :ack_due_at, :resolve_due_at)
        """,
        service_id=service_id,
        title=title,
        severity=severity,
        error_count=error_count,
        sample_message=sample_message,
        opened_at=opened_at,
        ack_due_at=ack_due_at,
        resolve_due_at=resolve_due_at,
    )


def get(conn: Connection, incident_id: int) -> dict | None:
    return _normalize(fetch_one(conn, _SELECT + " WHERE i.id = :id", id=incident_id))


def get_for_update(conn: Connection, incident_id: int) -> dict | None:
    """Lock the row on PostgreSQL so concurrent transitions serialize."""
    lock = " FOR UPDATE OF i" if conn.dialect.name == "postgresql" else ""
    return _normalize(fetch_one(conn, _SELECT + " WHERE i.id = :id" + lock, id=incident_id))


def active_for_service(conn: Connection, service_id: int) -> dict | None:
    return _normalize(
        fetch_one(
            conn,
            _SELECT + " WHERE i.service_id = :sid"
            " AND i.status IN ('open', 'acknowledged', 'investigating')",
            sid=service_id,
        )
    )


def search(
    conn: Connection,
    *,
    status: str | None = None,
    severity: str | None = None,
    service: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    clauses, params = [], {"limit": limit, "offset": offset}
    if status:
        clauses.append("i.status = :status")
        params["status"] = status
    if severity:
        clauses.append("i.severity = :severity")
        params["severity"] = severity
    if service:
        clauses.append("s.name = :service")
        params["service"] = service
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        _SELECT
        + where
        + " ORDER BY CASE i.status WHEN 'closed' THEN 1 WHEN 'resolved' THEN 1 ELSE 0 END,"
        " i.severity, i.opened_at DESC, i.id DESC LIMIT :limit OFFSET :offset"
    )
    return [_normalize(r) for r in fetch_all(conn, sql, **params)]


def update_fields(conn: Connection, incident_id: int, **fields) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "acknowledged_at",
        "resolved_at",
        "closed_at",
        "assignee_id",
        "resolution_note",
        "severity",
        "error_count",
        "sample_message",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"cannot update columns: {sorted(unknown)}")
    assignments = ", ".join(f"{col} = :{col}" for col in fields)
    conn.execute(
        text(f"UPDATE incidents SET {assignments} WHERE id = :id"), {**fields, "id": incident_id}
    )


def add_errors(conn: Connection, incident_id: int, count: int, sample: str | None) -> None:
    conn.execute(
        text(
            "UPDATE incidents SET error_count = error_count + :count,"
            " sample_message = COALESCE(:sample, sample_message) WHERE id = :id"
        ),
        {"count": count, "sample": sample, "id": incident_id},
    )
