"""Operational reports, written as plain SQL (JOIN / GROUP BY / CASE).

Every report takes a ``since`` lower bound on incident open time so the
dashboard can show "last 7 days", "last 30 days" and so on.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, seconds_between


def _num(value, digits: int = 1):
    return None if value is None else round(float(value), digits)


def sla_breaches(conn: Connection, *, since: datetime, now: datetime) -> list[dict]:
    """Per service and severity: how many incidents missed the ack/resolve SLA.

    An unacknowledged or unresolved incident counts as breached once its
    deadline is in the past, not only after it is finally handled.
    """
    rows = fetch_all(
        conn,
        """
        SELECT s.name   AS service,
               i.severity,
               COUNT(*) AS incidents,
               SUM(CASE WHEN COALESCE(i.acknowledged_at, :now) > i.ack_due_at
                        THEN 1 ELSE 0 END) AS ack_breaches,
               SUM(CASE WHEN COALESCE(i.resolved_at, :now) > i.resolve_due_at
                        THEN 1 ELSE 0 END) AS resolve_breaches
        FROM incidents i
        JOIN services s ON s.id = i.service_id
        WHERE i.opened_at >= :since
        GROUP BY s.name, i.severity
        ORDER BY resolve_breaches DESC, ack_breaches DESC, s.name, i.severity
        """,
        since=since,
        now=now,
    )
    for row in rows:
        row["ack_breaches"] = int(row["ack_breaches"] or 0)
        row["resolve_breaches"] = int(row["resolve_breaches"] or 0)
        row["breach_rate"] = _num(100.0 * row["resolve_breaches"] / row["incidents"])
    return rows


def mean_time_to_resolve(conn: Connection, *, since: datetime) -> list[dict]:
    """MTTA and MTTR in minutes per service and severity (resolved incidents only)."""
    dialect = conn.dialect.name
    ttr = seconds_between(dialect, "i.opened_at", "i.resolved_at")
    tta = seconds_between(dialect, "i.opened_at", "i.acknowledged_at")
    rows = fetch_all(
        conn,
        f"""
        SELECT s.name   AS service,
               i.severity,
               COUNT(*) AS resolved,
               AVG({tta}) / 60.0 AS mtta_minutes,
               AVG({ttr}) / 60.0 AS mttr_minutes,
               MAX({ttr}) / 60.0 AS worst_minutes
        FROM incidents i
        JOIN services s ON s.id = i.service_id
        WHERE i.resolved_at IS NOT NULL
          AND i.opened_at >= :since
        GROUP BY s.name, i.severity
        ORDER BY mttr_minutes DESC, s.name
        """,
        since=since,
    )
    for row in rows:
        for key in ("mtta_minutes", "mttr_minutes", "worst_minutes"):
            row[key] = _num(row[key])
    return rows


def ai_acceptance(conn: Connection, *, since: datetime) -> dict:
    """How often engineers accept AI suggestions, split by LLM vs rules.

    Acceptance rate = (approved + edited) / reviewed. Edited suggestions count
    as accepted because the engineer kept and refined them; the 'as-is' rate
    shows how often no change was needed at all.
    """
    rows = fetch_all(
        conn,
        """
        SELECT a.source,
               COUNT(*) AS total,
               SUM(CASE WHEN a.status = 'pending'  THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN a.status = 'approved' THEN 1 ELSE 0 END) AS approved,
               SUM(CASE WHEN a.status = 'edited'   THEN 1 ELSE 0 END) AS edited,
               SUM(CASE WHEN a.status = 'rejected' THEN 1 ELSE 0 END) AS rejected
        FROM ai_suggestions a
        JOIN incidents i ON i.id = a.incident_id
        WHERE i.opened_at >= :since
        GROUP BY a.source
        ORDER BY a.source
        """,
        since=since,
    )
    by_source = [_acceptance_row(r) for r in rows]
    overall = {"source": "all"}
    for key in ("total", "pending", "approved", "edited", "rejected"):
        overall[key] = sum(r[key] for r in by_source)
    return {"by_source": by_source, "overall": _acceptance_row(overall)}


def _acceptance_row(row: dict) -> dict:
    row = {k: (int(v) if k != "source" and v is not None else v) for k, v in row.items()}
    reviewed = row["approved"] + row["edited"] + row["rejected"]
    row["reviewed"] = reviewed
    row["acceptance_rate"] = _num(100.0 * (row["approved"] + row["edited"]) / reviewed) if reviewed else None
    row["as_is_rate"] = _num(100.0 * row["approved"] / reviewed) if reviewed else None
    return row


def runbook_usefulness(conn: Connection, *, since: datetime) -> list[dict]:
    """Which top-ranked runbooks led to accepted suggestions."""
    rows = fetch_all(
        conn,
        """
        SELECT r.slug, r.title,
               COUNT(*) AS times_top_ranked,
               SUM(CASE WHEN a.status IN ('approved', 'edited') THEN 1 ELSE 0 END) AS accepted
        FROM suggestion_runbooks sr
        JOIN runbooks r       ON r.id = sr.runbook_id
        JOIN ai_suggestions a ON a.id = sr.suggestion_id
        JOIN incidents i      ON i.id = a.incident_id
        WHERE sr.rank = 1
          AND i.opened_at >= :since
        GROUP BY r.slug, r.title
        ORDER BY times_top_ranked DESC, r.slug
        """,
        since=since,
    )
    for row in rows:
        row["accepted"] = int(row["accepted"] or 0)
    return rows


def status_overview(conn: Connection) -> dict:
    rows = fetch_all(
        conn,
        """
        SELECT status, severity, COUNT(*) AS n
        FROM incidents
        GROUP BY status, severity
        """,
    )
    overview: dict[str, dict[str, int]] = {}
    for row in rows:
        overview.setdefault(row["status"], {})[row["severity"]] = int(row["n"])
    return overview
