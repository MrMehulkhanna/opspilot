from __future__ import annotations

from flask import jsonify
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from opspilot import __version__
from opspilot.api import api_bp, json_body
from opspilot.app import get_engine, get_llm
from opspilot.errors import Conflict, ValidationError
from opspilot.store import engineers, runbooks, services


@api_bp.get("/health")
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 - health must never raise
        db_ok = False
    body = {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "llm": "configured" if get_llm() else "rules-only",
        "version": __version__,
    }
    return jsonify(body), 200 if db_ok else 503


@api_bp.get("/services")
def list_services():
    with get_engine().connect() as conn:
        return jsonify(services=services.list_all(conn))


@api_bp.get("/engineers")
def list_engineers():
    with get_engine().connect() as conn:
        return jsonify(engineers=engineers.list_all(conn))


@api_bp.post("/engineers")
def create_engineer():
    data = json_body()
    name, email = (data.get("name") or "").strip(), (data.get("email") or "").strip()
    role = data.get("role", "engineer")
    if not name or "@" not in email:
        raise ValidationError("name and a valid email are required")
    if role not in ("engineer", "lead"):
        raise ValidationError("role must be engineer or lead")
    try:
        with get_engine().begin() as conn:
            engineer_id = engineers.create(conn, name, email, role)
            engineer = engineers.get(conn, engineer_id)
    except IntegrityError as exc:
        raise Conflict(f"an engineer with email {email} already exists") from exc
    return jsonify(engineer), 201


@api_bp.get("/runbooks")
def list_runbooks():
    with get_engine().connect() as conn:
        rows = runbooks.list_all(conn)
    return jsonify(runbooks=[{k: r[k] for k in ("id", "slug", "title", "service_tag")} for r in rows])
