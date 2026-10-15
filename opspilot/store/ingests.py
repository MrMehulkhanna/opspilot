from __future__ import annotations

from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, insert_returning_id
from opspilot.timeutil import to_datetime, utcnow


def record(
    conn: Connection,
    *,
    source: str,
    lines_total: int,
    lines_parsed: int,
    error_lines: int,
    spikes_detected: int,
) -> int:
    return insert_returning_id(
        conn,
        """
        INSERT INTO log_ingests (source, lines_total, lines_parsed, error_lines,
                                 spikes_detected, created_at)
        VALUES (:source, :lines_total, :lines_parsed, :error_lines,
                :spikes_detected, :created_at)
        """,
        source=source[:200],
        lines_total=lines_total,
        lines_parsed=lines_parsed,
        error_lines=error_lines,
        spikes_detected=spikes_detected,
        created_at=utcnow(),
    )


def recent(conn: Connection, limit: int = 10) -> list[dict]:
    rows = fetch_all(
        conn, "SELECT * FROM log_ingests ORDER BY created_at DESC, id DESC LIMIT :n", n=limit
    )
    for row in rows:
        row["created_at"] = to_datetime(row["created_at"])
    return rows
