from datetime import timedelta

import pytest

from opspilot import incidents
from opspilot.errors import Conflict, NotFound, ValidationError
from opspilot.store import engineers, events

from .conftest import T0


@pytest.fixture
def conn(engine):
    with engine.begin() as c:
        yield c


@pytest.fixture
def asha(conn):
    return engineers.create(conn, "Asha Rao", "asha@example.com", role="lead")


def _open(conn, service="payments-api", severity="SEV2", at=T0):
    return incidents.open_incident(
        conn, service_name=service, title="Error spike", severity=severity, opened_at=at
    )


def test_open_incident_sets_sla_deadlines(conn):
    inc = _open(conn, severity="SEV1")
    assert inc["status"] == "open"
    assert inc["service_name"] == "payments-api"
    assert inc["ack_due_at"] == T0 + timedelta(minutes=15)
    assert inc["resolve_due_at"] == T0 + timedelta(hours=4)


def test_open_incident_registers_unknown_service(conn):
    inc = _open(conn, service="brand-new-svc")
    assert inc["service_team"] == "unassigned"


def test_open_incident_rejects_bad_severity(conn):
    with pytest.raises(ValidationError):
        _open(conn, severity="P1")


def test_second_active_incident_for_service_conflicts(conn):
    _open(conn)
    with pytest.raises(Conflict):
        _open(conn)


def test_full_lifecycle_writes_audit_trail(conn, asha):
    inc = _open(conn)
    incidents.transition(conn, inc["id"], "acknowledged", actor_id=asha, at=T0 + timedelta(minutes=3))
    incidents.transition(conn, inc["id"], "investigating", actor_id=asha)
    incidents.transition(conn, inc["id"], "resolved", actor_id=asha, note="Rolled back deploy")
    final = incidents.transition(conn, inc["id"], "closed", actor_id=asha)

    assert final["status"] == "closed"
    assert final["acknowledged_at"] == T0 + timedelta(minutes=3)
    assert final["resolution_note"] == "Rolled back deploy"
    assert final["closed_at"] is not None
    trail = events.for_incident(conn, inc["id"])
    assert [e["kind"] for e in trail] == ["created"] + ["status_change"] * 4
    assert trail[-1]["to_status"] == "closed"
    assert trail[1]["actor_name"] == "Asha Rao"


def test_acknowledge_auto_assigns_actor(conn, asha):
    inc = _open(conn)
    acked = incidents.transition(conn, inc["id"], "acknowledged", actor_id=asha)
    assert acked["assignee_id"] == asha


def test_illegal_transition_is_conflict(conn):
    inc = _open(conn)
    with pytest.raises(Conflict, match="cannot move"):
        incidents.transition(conn, inc["id"], "closed")


def test_transition_missing_incident(conn):
    with pytest.raises(NotFound):
        incidents.transition(conn, 12345, "acknowledged")


def test_reopen_clears_resolved_at(conn):
    inc = _open(conn)
    incidents.transition(conn, inc["id"], "acknowledged")
    incidents.transition(conn, inc["id"], "resolved", note="restarted pods")
    reopened = incidents.transition(conn, inc["id"], "investigating", note="errors are back")
    assert reopened["status"] == "investigating"
    assert reopened["resolved_at"] is None


def test_reopen_blocked_when_newer_incident_active(conn):
    inc = _open(conn)
    incidents.transition(conn, inc["id"], "acknowledged")
    incidents.transition(conn, inc["id"], "resolved", note="hotfix")
    _open(conn, at=T0 + timedelta(hours=1))
    with pytest.raises(Conflict, match="cannot reopen"):
        incidents.transition(conn, inc["id"], "investigating")


def test_assign_and_comment_are_audited(conn, asha):
    inc = _open(conn)
    incidents.assign(conn, inc["id"], asha, actor_id=asha)
    incidents.comment(conn, inc["id"], "Looking at DB pool metrics", actor_id=asha)
    kinds = [e["kind"] for e in events.for_incident(conn, inc["id"])]
    assert kinds == ["created", "assigned", "comment"]


def test_assign_unknown_engineer(conn):
    inc = _open(conn)
    with pytest.raises(NotFound):
        incidents.assign(conn, inc["id"], 999)


def test_empty_comment_rejected(conn):
    inc = _open(conn)
    with pytest.raises(ValidationError):
        incidents.comment(conn, inc["id"], "  ")
