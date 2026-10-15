from __future__ import annotations

from datetime import timedelta
from functools import wraps

from flask import current_app, flash, redirect, render_template, request, session, url_for

from opspilot import incidents, lifecycle, reports
from opspilot.analyzer.ingest import analyze_logs
from opspilot.app import get_engine, get_llm
from opspilot.errors import OpsPilotError
from opspilot.store import engineers, events, ingests, runbooks, suggestions
from opspilot.store import incidents as incident_store
from opspilot.timeutil import utcnow
from opspilot.triage import engine as triage
from opspilot.web import web_bp


def handles_domain_errors(view):
    """Show domain errors as a flash message and go back to the incident."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except OpsPilotError as exc:
            flash(str(exc), "error")
            return redirect(request.referrer or url_for("web.index"))

    return wrapper


def _engineer_id() -> int | None:
    return session.get("engineer_id")


@web_bp.get("/")
def index():
    status = request.args.get("status") or None
    severity = request.args.get("severity") or None
    if status not in (None, *lifecycle.STATUSES):
        status = None
    if severity not in (None, *lifecycle.SEVERITIES):
        severity = None
    now = utcnow()
    with get_engine().connect() as conn:
        rows = incident_store.search(conn, status=status, severity=severity, limit=100)
        overview = reports.status_overview(conn)
        team = engineers.list_all(conn)
    for row in rows:
        row["sla"] = lifecycle.sla_state(row, now)
    active = sum(sum(overview.get(s, {}).values()) for s in lifecycle.ACTIVE_STATUSES)
    breaching = sum(1 for r in rows if r["status"] in lifecycle.ACTIVE_STATUSES and r["sla"]["resolve_breached"])
    return render_template(
        "incidents.html",
        incidents=rows,
        overview=overview,
        active=active,
        breaching=breaching,
        team=team,
        status=status,
        severity=severity,
        statuses=lifecycle.STATUSES,
        severities=lifecycle.SEVERITIES,
    )


@web_bp.post("/act-as")
def act_as():
    raw = request.form.get("engineer_id", "")
    session["engineer_id"] = int(raw) if raw.isdigit() else None
    return redirect(request.referrer or url_for("web.index"))


@web_bp.get("/incidents/<int:incident_id>")
@handles_domain_errors
def incident_detail(incident_id: int):
    with get_engine().connect() as conn:
        incident = incidents.get_or_404(conn, incident_id)
        timeline = events.for_incident(conn, incident_id)
        ai = suggestions.for_incident(conn, incident_id)
        team = engineers.list_all(conn)
    return render_template(
        "incident.html",
        incident=incident,
        sla=lifecycle.sla_state(incident, utcnow()),
        timeline=timeline,
        suggestions=ai,
        team=team,
        next_statuses=sorted(lifecycle.allowed_next(incident["status"]), key=lifecycle.STATUSES.index),
        llm_enabled=get_llm() is not None,
    )


@web_bp.post("/incidents/<int:incident_id>/transition")
@handles_domain_errors
def incident_transition(incident_id: int):
    target = request.form.get("status", "")
    with get_engine().begin() as conn:
        incidents.transition(
            conn, incident_id, target, actor_id=_engineer_id(), note=request.form.get("note")
        )
    flash(f"Incident moved to {target}.", "ok")
    return redirect(url_for("web.incident_detail", incident_id=incident_id))


@web_bp.post("/incidents/<int:incident_id>/comment")
@handles_domain_errors
def incident_comment(incident_id: int):
    with get_engine().begin() as conn:
        incidents.comment(conn, incident_id, request.form.get("body", ""), actor_id=_engineer_id())
    return redirect(url_for("web.incident_detail", incident_id=incident_id))


@web_bp.post("/incidents/<int:incident_id>/suggest")
@handles_domain_errors
def incident_suggest(incident_id: int):
    with get_engine().begin() as conn:
        s = triage.suggest(conn, incident_id, llm=get_llm(), top_k=current_app.config["RUNBOOK_TOP_K"])
    flash(f"New {s['source'].upper()} suggestion ready for review.", "ok")
    return redirect(url_for("web.incident_detail", incident_id=incident_id))


@web_bp.post("/suggestions/<int:suggestion_id>/review")
@handles_domain_errors
def suggestion_review(suggestion_id: int):
    reviewer = _engineer_id()
    if reviewer is None:
        raise OpsPilotError("Choose who you are (top right) before reviewing a suggestion.")
    edited = [ln for ln in request.form.get("steps", "").splitlines() if ln.strip()]
    with get_engine().begin() as conn:
        s = triage.review(
            conn,
            suggestion_id,
            decision=request.form.get("decision", ""),
            reviewer_id=reviewer,
            edited_steps=edited or None,
            comment=request.form.get("comment") or None,
        )
    flash(f"Suggestion {s['status']}.", "ok")
    return redirect(url_for("web.incident_detail", incident_id=s["incident_id"]))


@web_bp.get("/reports")
def reports_page():
    days = request.args.get("days", "30")
    days = int(days) if days.isdigit() and 1 <= int(days) <= 365 else 30
    now = utcnow()
    since = now - timedelta(days=days)
    with get_engine().connect() as conn:
        data = {
            "sla": reports.sla_breaches(conn, since=since, now=now),
            "mttr": reports.mean_time_to_resolve(conn, since=since),
            "ai": reports.ai_acceptance(conn, since=since),
            "runbooks": reports.runbook_usefulness(conn, since=since),
        }
    return render_template("reports.html", days=days, **data)


@web_bp.route("/ingest", methods=["GET", "POST"])
@handles_domain_errors
def ingest():
    result = None
    if request.method == "POST":
        upload = request.files.get("file")
        pasted = request.form.get("text", "")
        if upload and upload.filename:
            lines = upload.read().decode("utf-8", errors="replace").splitlines()
            source = upload.filename
        else:
            lines, source = pasted.splitlines(), "pasted"
        if not any(line.strip() for line in lines):
            raise OpsPilotError("Upload a log file or paste some log lines.")
        cfg = current_app.config
        with get_engine().begin() as conn:
            result = analyze_logs(
                conn,
                lines,
                source=source,
                window_seconds=cfg["SPIKE_WINDOW_SECONDS"],
                threshold=cfg["SPIKE_THRESHOLD"],
            ).as_dict()
    with get_engine().connect() as conn:
        recent = ingests.recent(conn)
    return render_template("ingest.html", result=result, recent=recent)


@web_bp.get("/runbooks")
def runbook_list():
    with get_engine().connect() as conn:
        rows = runbooks.list_all(conn)
    return render_template("runbooks.html", runbooks=rows)
