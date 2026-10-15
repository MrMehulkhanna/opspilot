from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from opspilot.db import fetch_all, init_schema
from opspilot.store import engineers, services

from .conftest import T0


def _insert_incident(conn, service_id, status="open", severity="SEV2"):
    conn.execute(
        text(
            "INSERT INTO incidents (service_id, title, severity, status, opened_at,"
            " ack_due_at, resolve_due_at, closed_at)"
            " VALUES (:sid, 't', :sev, :status, :o, :a, :r, :c)"
        ),
        {
            "sid": service_id,
            "sev": severity,
            "status": status,
            "o": T0,
            "a": T0 + timedelta(minutes=30),
            "r": T0 + timedelta(hours=8),
            "c": T0 + timedelta(hours=9) if status == "closed" else None,
        },
    )


def test_schema_init_is_idempotent(engine):
    init_schema(engine)  # second run must not fail


def test_service_name_is_unique(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        services.create(conn, "payments-api")
        services.create(conn, "payments-api")


def test_engineer_email_unique_case_insensitive(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        engineers.create(conn, "Asha", "asha@example.com")
        engineers.create(conn, "Asha 2", "ASHA@example.com")


def test_severity_check_constraint(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        sid = services.create(conn, "auth")
        _insert_incident(conn, sid, severity="SEV7")


def test_status_check_constraint(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        sid = services.create(conn, "auth")
        _insert_incident(conn, sid, status="paused")


def test_foreign_key_enforced(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_incident(conn, service_id=999)


def test_only_one_active_incident_per_service(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        sid = services.create(conn, "search")
        _insert_incident(conn, sid, status="open")
        _insert_incident(conn, sid, status="investigating")


def test_closed_incidents_do_not_block_new_ones(engine):
    with engine.begin() as conn:
        sid = services.create(conn, "search")
        _insert_incident(conn, sid, status="closed")
        _insert_incident(conn, sid, status="open")
        rows = fetch_all(conn, "SELECT status FROM incidents ORDER BY id")
    assert [r["status"] for r in rows] == ["closed", "open"]
