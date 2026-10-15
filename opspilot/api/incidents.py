from __future__ import annotations

from flask import current_app, jsonify, request

from opspilot import incidents, lifecycle
from opspilot.api import actor_id, api_bp, int_arg, json_body, require_actor
from opspilot.app import get_engine, get_llm
from opspilot.errors import ValidationError
from opspilot.store import events, suggestions
from opspilot.store import incidents as store
from opspilot.timeutil import utcnow
from opspilot.triage import engine as triage


def _with_sla(incident: dict) -> dict:
    return {**incident, "sla": lifecycle.sla_state(incident, utcnow())}


@api_bp.get("/incidents")
def list_incidents():
    status = request.args.get("status")
    severity = request.args.get("severity")
    if status and status not in lifecycle.STATUSES:
        raise ValidationError(f"unknown status {status!r}")
    if severity and severity not in lifecycle.SEVERITIES:
        raise ValidationError(f"unknown severity {severity!r}")
    limit = int_arg("limit", 50, minimum=1, maximum=200)
    offset = int_arg("offset", 0)
    with get_engine().connect() as conn:
        rows = store.search(
            conn,
            status=status,
            severity=severity,
            service=request.args.get("service"),
            limit=limit,
            offset=offset,
        )
    return jsonify(incidents=[_with_sla(r) for r in rows], limit=limit, offset=offset)


@api_bp.post("/incidents")
def create_incident():
    data = json_body()
    with get_engine().begin() as conn:
        incident = incidents.open_incident(
            conn,
            service_name=(data.get("service") or "").strip().lower(),
            title=data.get("title") or "",
            severity=data.get("severity") or "SEV3",
            sample_message=data.get("sample_message"),
            actor_id=actor_id(),
        )
    return jsonify(_with_sla(incident)), 201


@api_bp.get("/incidents/<int:incident_id>")
def get_incident(incident_id: int):
    with get_engine().connect() as conn:
        incident = incidents.get_or_404(conn, incident_id)
        incident["events"] = events.for_incident(conn, incident_id)
        incident["suggestions"] = suggestions.for_incident(conn, incident_id)
    incident["allowed_transitions"] = sorted(lifecycle.allowed_next(incident["status"]))
    return jsonify(_with_sla(incident))


@api_bp.post("/incidents/<int:incident_id>/transition")
def transition_incident(incident_id: int):
    data = json_body()
    target = data.get("status")
    if not target:
        raise ValidationError("status is required")
    with get_engine().begin() as conn:
        incident = incidents.transition(
            conn, incident_id, target, actor_id=actor_id(), note=data.get("note")
        )
    return jsonify(_with_sla(incident))


@api_bp.post("/incidents/<int:incident_id>/assign")
def assign_incident(incident_id: int):
    data = json_body()
    engineer_id = data.get("engineer_id")
    if not isinstance(engineer_id, int):
        raise ValidationError("engineer_id must be an integer")
    with get_engine().begin() as conn:
        incident = incidents.assign(conn, incident_id, engineer_id, actor_id=actor_id())
    return jsonify(_with_sla(incident))


@api_bp.post("/incidents/<int:incident_id>/comments")
def comment_incident(incident_id: int):
    data = json_body()
    with get_engine().begin() as conn:
        incidents.comment(conn, incident_id, data.get("body") or "", actor_id=actor_id())
    return jsonify(ok=True), 201


@api_bp.post("/incidents/<int:incident_id>/suggestions")
def create_suggestion(incident_id: int):
    with get_engine().begin() as conn:
        suggestion = triage.suggest(
            conn, incident_id, llm=get_llm(), top_k=current_app.config["RUNBOOK_TOP_K"]
        )
    return jsonify(suggestion), 201


@api_bp.post("/suggestions/<int:suggestion_id>/review")
def review_suggestion(suggestion_id: int):
    data = json_body()
    steps = data.get("steps")
    if steps is not None and not (isinstance(steps, list) and all(isinstance(s, str) for s in steps)):
        raise ValidationError("steps must be a list of strings")
    with get_engine().begin() as conn:
        suggestion = triage.review(
            conn,
            suggestion_id,
            decision=data.get("decision") or "",
            reviewer_id=require_actor(),
            edited_steps=steps,
            comment=data.get("comment"),
        )
    return jsonify(suggestion)
