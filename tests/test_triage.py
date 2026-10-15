from pathlib import Path

import pytest

from opspilot import incidents
from opspilot.errors import Conflict, ValidationError
from opspilot.store import engineers, events
from opspilot.triage.engine import review, suggest
from opspilot.triage.llm import LLMError
from opspilot.triage.runbook_loader import load_directory, parse_runbook

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"


class FakeLLM:
    model = "fake-model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.prompts = reply, error, []

    def complete(self, system, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def conn(engine):
    with engine.begin() as c:
        load_directory(c, RUNBOOK_DIR)
        yield c


@pytest.fixture
def incident(conn):
    return incidents.open_incident(
        conn,
        service_name="orders-db",
        title="Error spike on orders-db: connection pool exhausted",
        severity="SEV2",
        sample_message="timeout acquiring connection: pool exhausted",
    )


@pytest.fixture
def ravi(conn):
    return engineers.create(conn, "Ravi Menon", "ravi@example.com")


def test_parse_runbook_front_matter():
    meta, body = parse_runbook("---\ntitle: Disk full\nservice: api\n---\n1. df -h\n")
    assert meta == {"title": "Disk full", "service": "api"}
    assert body == "1. df -h"


def test_rules_suggestion_cites_retrieved_runbook(conn, incident):
    s = suggest(conn, incident["id"])
    assert s["source"] == "rules"
    assert s["status"] == "pending"
    assert s["runbooks"][0]["slug"] == "db-connection-pool-exhausted"
    assert [r["rank"] for r in s["runbooks"]] == list(range(1, len(s["runbooks"]) + 1))


def test_llm_suggestion_used_when_valid(conn, incident):
    llm = FakeLLM('{"probable_cause": "Leaked sessions", "steps": ["Kill idle tx"], "severity": "SEV1"}')
    s = suggest(conn, incident["id"], llm=llm)
    assert (s["source"], s["model"], s["suggested_severity"]) == ("llm", "fake-model", "SEV1")
    assert "Database connection pool exhausted" in llm.prompts[0]


@pytest.mark.parametrize("llm", [FakeLLM("garbage"), FakeLLM(error=LLMError("timeout"))])
def test_falls_back_to_rules_when_llm_fails(conn, incident, llm):
    s = suggest(conn, incident["id"], llm=llm)
    assert s["source"] == "rules"
    trail = events.for_incident(conn, incident["id"])
    assert "fallback_reason" in trail[-1]["detail"]


def test_approve_keeps_suggested_steps_and_audits(conn, incident, ravi):
    s = suggest(conn, incident["id"])
    reviewed = review(conn, s["id"], decision="approve", reviewer_id=ravi)
    assert reviewed["status"] == "approved"
    assert reviewed["final_steps"] == s["suggested_steps"]
    last = events.for_incident(conn, incident["id"])[-1]
    assert (last["kind"], last["actor_name"]) == ("ai_approved", "Ravi Menon")


def test_edit_stores_engineer_steps(conn, incident, ravi):
    s = suggest(conn, incident["id"])
    reviewed = review(conn, s["id"], decision="edit", reviewer_id=ravi, edited_steps=["Do X", " "])
    assert reviewed["status"] == "edited"
    assert reviewed["final_steps"] == ["Do X"]


def test_reject_requires_reason(conn, incident, ravi):
    s = suggest(conn, incident["id"])
    with pytest.raises(ValidationError):
        review(conn, s["id"], decision="reject", reviewer_id=ravi)
    rejected = review(conn, s["id"], decision="reject", reviewer_id=ravi, comment="wrong service")
    assert rejected["status"] == "rejected" and rejected["final_steps"] is None


def test_suggestion_can_only_be_reviewed_once(conn, incident, ravi):
    s = suggest(conn, incident["id"])
    review(conn, s["id"], decision="approve", reviewer_id=ravi)
    with pytest.raises(Conflict):
        review(conn, s["id"], decision="approve", reviewer_id=ravi)


def test_closed_incident_cannot_be_triaged(conn, incident):
    incidents.transition(conn, incident["id"], "acknowledged")
    incidents.transition(conn, incident["id"], "resolved", note="pool size raised")
    incidents.transition(conn, incident["id"], "closed")
    with pytest.raises(Conflict):
        suggest(conn, incident["id"])
