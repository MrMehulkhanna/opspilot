from datetime import timedelta
from pathlib import Path

import pytest

from opspilot import incidents, reports
from opspilot.store import engineers
from opspilot.triage.engine import review, suggest
from opspilot.triage.runbook_loader import load_directory

from .conftest import T0

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"
SINCE = T0 - timedelta(days=1)


@pytest.fixture
def conn(engine):
    with engine.begin() as c:
        yield c


def _incident(conn, service, severity, ack_after=None, resolve_after=None, at=T0):
    inc = incidents.open_incident(
        conn, service_name=service, title="spike", severity=severity, opened_at=at
    )
    if ack_after is not None:
        incidents.transition(conn, inc["id"], "acknowledged", at=at + ack_after)
    if resolve_after is not None:
        incidents.transition(conn, inc["id"], "resolved", note="fixed", at=at + resolve_after)
    return inc


def test_sla_breach_report(conn):
    # SEV1: ack 15m / resolve 4h
    _incident(conn, "payments-api", "SEV1", timedelta(minutes=5), timedelta(hours=1))
    _incident(
        conn,
        "payments-api",
        "SEV1",
        timedelta(minutes=40),
        timedelta(hours=6),
        at=T0 + timedelta(days=1),
    )
    _incident(conn, "auth", "SEV3")  # never acknowledged
    rows = reports.sla_breaches(conn, since=SINCE, now=T0 + timedelta(days=5))
    by_key = {(r["service"], r["severity"]): r for r in rows}

    pay = by_key[("payments-api", "SEV1")]
    assert (pay["incidents"], pay["ack_breaches"], pay["resolve_breaches"]) == (2, 1, 1)
    assert pay["breach_rate"] == 50.0
    auth = by_key[("auth", "SEV3")]
    assert (auth["ack_breaches"], auth["resolve_breaches"]) == (1, 1)


def test_sla_report_respects_since(conn):
    _incident(conn, "auth", "SEV3")
    assert reports.sla_breaches(conn, since=T0 + timedelta(hours=1), now=T0) == []


def test_mean_time_to_resolve(conn):
    _incident(conn, "search", "SEV2", timedelta(minutes=10), timedelta(minutes=60))
    _incident(
        conn,
        "search",
        "SEV2",
        timedelta(minutes=20),
        timedelta(minutes=120),
        at=T0 + timedelta(days=1),
    )
    _incident(conn, "auth", "SEV2", timedelta(minutes=5))  # unresolved: excluded
    rows = reports.mean_time_to_resolve(conn, since=SINCE)
    assert len(rows) == 1
    row = rows[0]
    assert (row["service"], row["resolved"]) == ("search", 2)
    assert row["mtta_minutes"] == pytest.approx(15.0)
    assert row["mttr_minutes"] == pytest.approx(90.0)
    assert row["worst_minutes"] == pytest.approx(120.0)


def test_ai_acceptance_rate_and_runbook_usefulness(conn):
    load_directory(conn, RUNBOOK_DIR)
    lead = engineers.create(conn, "Lead", "lead@example.com", role="lead")
    decisions = [("approve", None), ("edit", ["custom step"]), ("reject", None), (None, None)]
    for n, (decision, steps) in enumerate(decisions):
        inc = incidents.open_incident(
            conn,
            service_name=f"orders-db-{n}",
            title="connection pool exhausted",
            severity="SEV2",
            opened_at=T0,
        )
        s = suggest(conn, inc["id"])
        if decision:
            review(
                conn,
                s["id"],
                decision=decision,
                reviewer_id=lead,
                edited_steps=steps,
                comment="not relevant" if decision == "reject" else None,
            )

    result = reports.ai_acceptance(conn, since=SINCE)
    overall = result["overall"]
    assert (overall["total"], overall["reviewed"], overall["pending"]) == (4, 3, 1)
    assert overall["acceptance_rate"] == pytest.approx(66.7)
    assert overall["as_is_rate"] == pytest.approx(33.3)
    assert [r["source"] for r in result["by_source"]] == ["rules"]

    useful = reports.runbook_usefulness(conn, since=SINCE)
    assert useful[0]["slug"] == "db-connection-pool-exhausted"
    assert (useful[0]["times_top_ranked"], useful[0]["accepted"]) == (4, 2)


def test_acceptance_with_no_suggestions(conn):
    result = reports.ai_acceptance(conn, since=SINCE)
    assert result["overall"]["acceptance_rate"] is None


def test_status_overview(conn):
    _incident(conn, "a", "SEV1")
    _incident(conn, "b", "SEV1", timedelta(minutes=1))
    _incident(conn, "c", "SEV3")
    assert reports.status_overview(conn) == {
        "open": {"SEV1": 1, "SEV3": 1},
        "acknowledged": {"SEV1": 1},
    }
