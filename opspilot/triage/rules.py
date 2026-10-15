"""Rule-based triage: the deterministic fallback when the LLM is unavailable.

Each rule matches keywords in the incident text and contributes a probable
cause. Steps come from the best retrieved runbook when there is one, so the
fallback still benefits from retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opspilot.triage.retriever import RetrievedRunbook


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern
    cause: str
    severity: str | None = None


RULES: tuple[Rule, ...] = (
    Rule(
        re.compile(r"pool exhausted|too many connections|acquir\w* connection", re.I),
        "Database connection pool exhaustion (leaked or long-running connections, or a "
        "traffic surge beyond pool capacity).",
    ),
    Rule(
        re.compile(r"no space left|disk full", re.I),
        "A host ran out of disk space, so writes are failing.",
        "SEV2",
    ),
    Rule(
        re.compile(r"out ?of ?memory|oomkilled|killed process", re.I),
        "Processes are being killed for exceeding memory limits, possibly a memory leak.",
    ),
    Rule(
        re.compile(r"invalid token|signature|jwt|unauthori[sz]ed|401", re.I),
        "Token validation is failing, often after a signing-key rotation or clock skew.",
    ),
    Rule(
        re.compile(r"resolve host|name resolution|nxdomain|service not known", re.I),
        "Hostname resolution is failing (DNS or service discovery).",
    ),
    Rule(
        re.compile(r"queue|consumer lag|dead.?letter", re.I),
        "A message queue is backing up because consumers are slow, stuck or down.",
    ),
    Rule(
        re.compile(r"slow query|statement timeout|query cancel", re.I),
        "Slow database queries, possibly a missing index or a plan regression.",
    ),
    Rule(
        re.compile(r"time ?out|timed out|deadline exceeded", re.I),
        "A downstream dependency is responding slowly or not at all.",
    ),
)

GENERIC_STEPS = [
    "Check whether a deploy or config change lines up with the start of the errors.",
    "Look at the service dashboard for saturation (CPU, memory, connections).",
    "Check the health of the service's direct dependencies.",
    "Roll back the most recent change if customer impact is high.",
]

_STEP_LINE = re.compile(r"^\s*\d+\.\s+(.*\S)\s*$")


def runbook_steps(body: str, limit: int = 5) -> list[str]:
    steps = [m.group(1) for line in body.splitlines() if (m := _STEP_LINE.match(line))]
    return steps[:limit]


def rule_based_suggestion(incident: dict, retrieved: list[RetrievedRunbook]) -> dict:
    haystack = " ".join(
        str(incident.get(k) or "") for k in ("title", "sample_message", "service_name")
    )
    matched = [rule for rule in RULES if rule.pattern.search(haystack)]
    if matched:
        cause = " ".join(rule.cause for rule in matched[:2])
    else:
        cause = "No known failure pattern matched; investigate recent changes and dependencies."

    severity = next((r.severity for r in matched if r.severity), None) or incident.get("severity")
    steps = runbook_steps(retrieved[0].body) if retrieved else []
    if not steps:
        steps = list(GENERIC_STEPS)
    return {"probable_cause": cause, "steps": steps, "severity": severity}
