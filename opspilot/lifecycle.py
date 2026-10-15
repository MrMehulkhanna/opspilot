"""Incident lifecycle: allowed status transitions and SLA policy.

Pure functions with no database access, so the rules are easy to test and
reason about in isolation.

    open -> acknowledged -> investigating -> resolved -> closed
                 \\______________________/      |
                                                v
                                    (reopen) investigating
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

STATUSES = ("open", "acknowledged", "investigating", "resolved", "closed")
ACTIVE_STATUSES = ("open", "acknowledged", "investigating")
SEVERITIES = ("SEV1", "SEV2", "SEV3")

TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"acknowledged"}),
    "acknowledged": frozenset({"investigating", "resolved"}),
    "investigating": frozenset({"resolved"}),
    "resolved": frozenset({"closed", "investigating"}),
    "closed": frozenset(),
}


class TransitionError(ValueError):
    """Raised when a status change is not allowed by the lifecycle."""


@dataclass(frozen=True)
class SlaPolicy:
    ack_within: timedelta
    resolve_within: timedelta


SLA_POLICIES: dict[str, SlaPolicy] = {
    "SEV1": SlaPolicy(ack_within=timedelta(minutes=15), resolve_within=timedelta(hours=4)),
    "SEV2": SlaPolicy(ack_within=timedelta(minutes=30), resolve_within=timedelta(hours=12)),
    "SEV3": SlaPolicy(ack_within=timedelta(hours=4), resolve_within=timedelta(hours=72)),
}


def allowed_next(status: str) -> frozenset[str]:
    if status not in TRANSITIONS:
        raise TransitionError(f"unknown status {status!r}")
    return TRANSITIONS[status]


def check_transition(current: str, target: str, *, note: str | None = None) -> None:
    """Validate a transition, raising TransitionError with a readable reason."""
    if target not in TRANSITIONS:
        raise TransitionError(f"unknown status {target!r}")
    if target not in allowed_next(current):
        allowed = ", ".join(sorted(allowed_next(current))) or "none (terminal)"
        raise TransitionError(
            f"cannot move incident from {current!r} to {target!r}; allowed: {allowed}"
        )
    if target == "resolved" and not (note and note.strip()):
        raise TransitionError("a resolution note is required to resolve an incident")


def sla_deadlines(severity: str, opened_at: datetime) -> tuple[datetime, datetime]:
    """Return (ack_due_at, resolve_due_at) for a newly opened incident."""
    if severity not in SLA_POLICIES:
        raise ValueError(f"unknown severity {severity!r}")
    policy = SLA_POLICIES[severity]
    return opened_at + policy.ack_within, opened_at + policy.resolve_within


def sla_state(incident: dict, now: datetime) -> dict:
    """Compute live SLA flags for an incident row.

    A deadline is breached when the milestone happened late, or when it has
    not happened yet and the deadline is already in the past.
    """
    ack_at = incident.get("acknowledged_at")
    resolved_at = incident.get("resolved_at")
    ack_due = incident["ack_due_at"]
    resolve_due = incident["resolve_due_at"]

    ack_breached = (ack_at or now) > ack_due
    resolve_breached = (resolved_at or now) > resolve_due
    if resolved_at is None and incident.get("status") in ACTIVE_STATUSES:
        remaining = (resolve_due - now).total_seconds()
    else:
        remaining = None
    return {
        "ack_breached": ack_breached,
        "resolve_breached": resolve_breached,
        "resolve_seconds_remaining": remaining,
    }
