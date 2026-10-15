from opspilot.analyzer.ingest import analyze_logs
from opspilot.store import events, ingests
from opspilot.store import incidents as incident_store


def _lines(service, count, minute=0, msg="Timeout talking to ledger-db"):
    return [f"2026-10-01T09:{minute:02d}:{i:02d}Z ERROR {service} {msg}" for i in range(count)]


def test_spike_opens_incident_and_records_ingest(engine):
    lines = _lines("payments-api", 25) + ["2026-10-01T09:00:30Z INFO payments-api ok", "garbage"]
    with engine.begin() as conn:
        result = analyze_logs(conn, lines, source="app.log")
        incident = incident_store.get(conn, result.opened[0])
        trail = events.for_incident(conn, incident["id"])
        batch = ingests.recent(conn)[0]

    assert result.as_dict()["spikes_detected"] == 1
    assert (result.lines_total, result.lines_parsed, result.error_lines) == (27, 26, 25)
    assert incident["severity"] == "SEV2"
    assert incident["error_count"] == 25
    assert incident["title"].startswith("Error spike on payments-api")
    assert [e["kind"] for e in trail] == ["created", "spike"]
    assert batch["source"] == "app.log"


def test_repeat_spike_attaches_to_active_incident(engine):
    with engine.begin() as conn:
        first = analyze_logs(conn, _lines("auth", 12))
        second = analyze_logs(conn, _lines("auth", 15, minute=10))
        incident = incident_store.get(conn, first.opened[0])
    assert second.opened == []
    assert second.updated == first.opened
    assert incident["error_count"] == 27


def test_quiet_logs_open_nothing(engine):
    with engine.begin() as conn:
        result = analyze_logs(conn, _lines("search", 5))
    assert result.spikes == 0 and result.opened == []
