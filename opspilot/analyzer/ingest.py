"""Turn a batch of log lines into incidents.

A spike on a service with no active incident opens a new one. A spike on a
service that already has an active incident is attached to it (error count
and a 'spike' audit event) instead of creating a duplicate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy.engine import Connection

from opspilot import incidents
from opspilot.analyzer.parser import parse_line
from opspilot.analyzer.window import detect_spikes, severity_for
from opspilot.store import events, ingests, services
from opspilot.store import incidents as incident_store


@dataclass
class IngestResult:
    ingest_id: int
    lines_total: int
    lines_parsed: int
    error_lines: int
    spikes: int
    opened: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ingest_id": self.ingest_id,
            "lines_total": self.lines_total,
            "lines_parsed": self.lines_parsed,
            "error_lines": self.error_lines,
            "spikes_detected": self.spikes,
            "incidents_opened": self.opened,
            "incidents_updated": self.updated,
        }


def analyze_logs(
    conn: Connection,
    lines: Iterable[str],
    *,
    source: str = "upload",
    window_seconds: int = 60,
    threshold: int = 10,
) -> IngestResult:
    total = 0
    records = []
    for line in lines:
        if not line.strip():
            continue
        total += 1
        record = parse_line(line)
        if record is not None:
            records.append(record)

    error_lines = sum(1 for r in records if r.is_error)
    spikes = detect_spikes(records, window_seconds=window_seconds, threshold=threshold)

    opened: list[int] = []
    updated: list[int] = []
    for spike in spikes:
        service = services.get_or_create(conn, spike.service)
        active = incident_store.active_for_service(conn, service["id"])
        detail = {
            "started_at": spike.started_at.isoformat(),
            "ended_at": spike.ended_at.isoformat(),
            "peak_errors_in_window": spike.peak_errors_in_window,
            "window_seconds": window_seconds,
            "total_errors": spike.total_errors,
        }
        if active:
            incident_store.add_errors(conn, active["id"], spike.total_errors, spike.top_message)
            events.record(conn, active["id"], "spike", detail=detail, at=spike.ended_at)
            updated.append(active["id"])
            continue

        title = f"Error spike on {spike.service}: {spike.top_message}"[:200]
        incident = incidents.open_incident(
            conn,
            service_name=spike.service,
            title=title,
            severity=severity_for(spike, threshold),
            opened_at=spike.started_at,
            error_count=spike.total_errors,
            sample_message=spike.top_message,
        )
        events.record(conn, incident["id"], "spike", detail=detail, at=spike.ended_at)
        opened.append(incident["id"])

    ingest_id = ingests.record(
        conn,
        source=source,
        lines_total=total,
        lines_parsed=len(records),
        error_lines=error_lines,
        spikes_detected=len(spikes),
    )
    return IngestResult(ingest_id, total, len(records), error_lines, len(spikes), opened, updated)
