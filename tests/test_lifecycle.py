from datetime import datetime, timedelta

import pytest

from opspilot.lifecycle import (
    TransitionError,
    allowed_next,
    check_transition,
    sla_deadlines,
    sla_state,
)

T0 = datetime(2026, 10, 1, 9, 0, 0)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("open", "acknowledged"),
        ("acknowledged", "investigating"),
        ("acknowledged", "resolved"),
        ("investigating", "resolved"),
        ("resolved", "closed"),
        ("resolved", "investigating"),
    ],
)
def test_valid_transitions(current, target):
    check_transition(current, target, note="fixed config")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("open", "resolved"),
        ("open", "closed"),
        ("investigating", "open"),
        ("closed", "investigating"),
        ("resolved", "acknowledged"),
    ],
)
def test_invalid_transitions(current, target):
    with pytest.raises(TransitionError):
        check_transition(current, target, note="x")


def test_closed_is_terminal():
    assert allowed_next("closed") == frozenset()


def test_resolve_requires_note():
    with pytest.raises(TransitionError, match="resolution note"):
        check_transition("investigating", "resolved", note="   ")


def test_unknown_status_rejected():
    with pytest.raises(TransitionError, match="unknown status"):
        check_transition("open", "paused")


def test_sla_deadlines_scale_with_severity():
    sev1_ack, sev1_res = sla_deadlines("SEV1", T0)
    sev3_ack, sev3_res = sla_deadlines("SEV3", T0)
    assert sev1_ack == T0 + timedelta(minutes=15)
    assert sev1_res == T0 + timedelta(hours=4)
    assert sev3_ack > sev1_ack and sev3_res > sev1_res


def test_sla_deadlines_unknown_severity():
    with pytest.raises(ValueError):
        sla_deadlines("SEV9", T0)


def test_sla_state_breaches_when_unacknowledged_past_deadline():
    ack_due, res_due = sla_deadlines("SEV1", T0)
    incident = {"status": "open", "ack_due_at": ack_due, "resolve_due_at": res_due}
    state = sla_state(incident, T0 + timedelta(minutes=20))
    assert state["ack_breached"] is True
    assert state["resolve_breached"] is False
    assert state["resolve_seconds_remaining"] == pytest.approx(
        (res_due - (T0 + timedelta(minutes=20))).total_seconds()
    )


def test_sla_state_uses_actual_timestamps_once_reached():
    ack_due, res_due = sla_deadlines("SEV2", T0)
    incident = {
        "status": "resolved",
        "ack_due_at": ack_due,
        "resolve_due_at": res_due,
        "acknowledged_at": T0 + timedelta(minutes=5),
        "resolved_at": T0 + timedelta(hours=1),
    }
    state = sla_state(incident, T0 + timedelta(days=10))
    assert state == {
        "ack_breached": False,
        "resolve_breached": False,
        "resolve_seconds_remaining": None,
    }
