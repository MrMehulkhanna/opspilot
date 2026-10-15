from pathlib import Path

import pytest

from opspilot.app import create_app
from opspilot.config import Config
from opspilot.triage.runbook_loader import load_directory

SPIKE = [f"2026-10-01T09:00:{i:02d}Z ERROR orders-db connection pool exhausted" for i in range(30)]


@pytest.fixture
def engineer(client):
    res = client.post("/api/v1/engineers", json={"name": "Asha", "email": "asha@example.com"})
    return res.get_json()["id"]


@pytest.fixture
def incident_id(client):
    res = client.post("/api/v1/logs/analyze", json={"lines": SPIKE, "source": "t.log"})
    return res.get_json()["incidents_opened"][0]


def test_health(client):
    body = client.get("/api/v1/health").get_json()
    assert body["status"] == "ok" and body["llm"] == "rules-only"


def test_analyze_logs_opens_incident(client):
    res = client.post("/api/v1/logs/analyze", json={"lines": SPIKE})
    assert res.status_code == 201
    assert res.get_json()["spikes_detected"] == 1
    listing = client.get("/api/v1/incidents?status=open").get_json()
    assert listing["incidents"][0]["service_name"] == "orders-db"
    assert "resolve_breached" in listing["incidents"][0]["sla"]


def test_analyze_accepts_raw_text_and_validates(client):
    assert client.post("/api/v1/logs/analyze", data="\n".join(SPIKE)).status_code == 201
    assert client.post("/api/v1/logs/analyze", json={"lines": "nope"}).status_code == 422


def test_lifecycle_over_api(client, engineer, incident_id):
    hdr = {"X-Engineer-Id": str(engineer)}
    url = f"/api/v1/incidents/{incident_id}"
    assert client.post(url + "/transition", json={"status": "acknowledged"}, headers=hdr).status_code == 200
    no_note = client.post(url + "/transition", json={"status": "resolved"}, headers=hdr)
    assert no_note.status_code == 409
    assert "resolution note" in no_note.get_json()["error"]
    ok = client.post(url + "/transition", json={"status": "resolved", "note": "pool raised"}, headers=hdr)
    assert ok.get_json()["status"] == "resolved"
    detail = client.get(url).get_json()
    assert detail["allowed_transitions"] == ["closed", "investigating"]
    assert [e["kind"] for e in detail["events"]][-2:] == ["status_change", "status_change"]


def test_invalid_transition_returns_409(client, incident_id):
    res = client.post(f"/api/v1/incidents/{incident_id}/transition", json={"status": "closed"})
    assert res.status_code == 409
    assert "cannot move" in res.get_json()["error"]


def test_suggest_and_review_requires_engineer(app, client, engineer, incident_id):
    with app.extensions["opspilot.engine"].begin() as conn:
        load_directory(conn, Path(__file__).resolve().parent.parent / "runbooks")
    s = client.post(f"/api/v1/incidents/{incident_id}/suggestions").get_json()
    assert s["source"] == "rules" and s["runbooks"]
    url = f"/api/v1/suggestions/{s['id']}/review"
    assert client.post(url, json={"decision": "approve"}).status_code == 422
    res = client.post(url, json={"decision": "approve"}, headers={"X-Engineer-Id": str(engineer)})
    assert res.get_json()["status"] == "approved"
    report = client.get("/api/v1/reports/ai-acceptance").get_json()
    assert report["overall"]["acceptance_rate"] == 100.0


def test_reports_endpoints(client, incident_id):
    for path in ("sla-breaches", "mttr", "runbooks"):
        assert client.get(f"/api/v1/reports/{path}?days=7").status_code == 200
    assert client.get("/api/v1/reports/mttr?days=0").status_code == 422


def test_unknown_incident_404(client):
    assert client.get("/api/v1/incidents/999").status_code == 404


def test_duplicate_engineer_conflict(client, engineer):
    res = client.post("/api/v1/engineers", json={"name": "A", "email": "ASHA@example.com"})
    assert res.status_code == 409


def test_api_key_enforced_when_configured(db_url):
    app = create_app(Config(DATABASE_URL=db_url, API_KEY="s3cret", LLM_API_KEY=""))
    client = app.test_client()
    assert client.get("/api/v1/incidents").status_code == 401
    assert client.get("/api/v1/incidents", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    app.extensions["opspilot.engine"].dispose()
