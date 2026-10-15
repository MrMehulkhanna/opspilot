"""Incident operations: every state change goes through here.

Each function runs inside the caller's transaction, validates against the
lifecycle rules and writes an audit event alongside the change.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from opspilot import lifecycle
from opspilot.errors import Conflict, NotFound, ValidationError
from opspilot.store import engineers, events, services
from opspilot.store import incidents as store
from opspilot.timeutil import utcnow


def open_incident(
    conn: Connection,
    *,
    service_name: str,
    title: str,
    severity: str,
    opened_at: datetime | None = None,
    error_count: int = 0,
    sample_message: str | None = None,
    actor_id: int | None = None,
) -> dict:
    if severity not in lifecycle.SEVERITIES:
        raise ValidationError(f"severity must be one of {', '.join(lifecycle.SEVERITIES)}")
    if not title or not title.strip():
        raise ValidationError("title is required")

    opened_at = opened_at or utcnow()
    service = services.get_or_create(conn, service_name)
    if store.active_for_service(conn, service["id"]):
        raise Conflict(f"service {service_name!r} already has an active incident")

    ack_due, resolve_due = lifecycle.sla_deadlines(severity, opened_at)
    try:
        incident_id = store.insert(
            conn,
            service_id=service["id"],
            title=title.strip()[:200],
            severity=severity,
            opened_at=opened_at,
            ack_due_at=ack_due,
            resolve_due_at=resolve_due,
            error_count=error_count,
            sample_message=sample_message,
        )
    except IntegrityError as exc:
        # Lost a race with a concurrent writer; the partial unique index
        # caught it. The caller's transaction is rolled back.
        raise Conflict(f"service {service_name!r} already has an active incident") from exc

    events.record(
        conn,
        incident_id,
        "created",
        actor_id=actor_id,
        to_status="open",
        detail={"severity": severity, "error_count": error_count},
        at=opened_at,
    )
    return store.get(conn, incident_id)


def transition(
    conn: Connection,
    incident_id: int,
    target: str,
    *,
    actor_id: int | None = None,
    note: str | None = None,
    at: datetime | None = None,
) -> dict:
    incident = store.get_for_update(conn, incident_id)
    if incident is None:
        raise NotFound(f"incident {incident_id} not found")

    current = incident["status"]
    try:
        lifecycle.check_transition(current, target, note=note)
    except lifecycle.TransitionError as exc:
        raise Conflict(str(exc)) from exc

    at = at or utcnow()
    fields: dict = {"status": target}
    if target == "acknowledged":
        fields["acknowledged_at"] = at
        if actor_id and not incident["assignee_id"]:
            fields["assignee_id"] = actor_id
    elif target == "resolved":
        fields["resolved_at"] = at
        fields["resolution_note"] = note.strip()
    elif target == "closed":
        fields["closed_at"] = at
    elif target == "investigating" and current == "resolved":
        # Reopen: the fix did not hold. Only allowed if no newer incident
        # is already active for the same service.
        other = store.active_for_service(conn, incident["service_id"])
        if other and other["id"] != incident_id:
            raise Conflict(
                f"cannot reopen: incident {other['id']} is already active for this service"
            )
        fields["resolved_at"] = None

    store.update_fields(conn, incident_id, **fields)
    events.record(
        conn,
        incident_id,
        "status_change",
        actor_id=actor_id,
        from_status=current,
        to_status=target,
        detail={"note": note.strip()} if note and note.strip() else None,
        at=at,
    )
    return store.get(conn, incident_id)


def assign(conn: Connection, incident_id: int, engineer_id: int, *, actor_id: int | None = None):
    incident = store.get_for_update(conn, incident_id)
    if incident is None:
        raise NotFound(f"incident {incident_id} not found")
    if incident["status"] == "closed":
        raise Conflict("closed incidents cannot be reassigned")
    engineer = engineers.get(conn, engineer_id)
    if engineer is None:
        raise NotFound(f"engineer {engineer_id} not found")
    store.update_fields(conn, incident_id, assignee_id=engineer_id)
    events.record(
        conn,
        incident_id,
        "assigned",
        actor_id=actor_id,
        detail={"assignee_id": engineer_id, "assignee": engineer["name"]},
    )
    return store.get(conn, incident_id)


def comment(conn: Connection, incident_id: int, body: str, *, actor_id: int | None = None):
    if store.get(conn, incident_id) is None:
        raise NotFound(f"incident {incident_id} not found")
    if not body or not body.strip():
        raise ValidationError("comment cannot be empty")
    events.record(conn, incident_id, "comment", actor_id=actor_id, detail={"body": body.strip()})


def get_or_404(conn: Connection, incident_id: int) -> dict:
    incident = store.get(conn, incident_id)
    if incident is None:
        raise NotFound(f"incident {incident_id} not found")
    return incident
