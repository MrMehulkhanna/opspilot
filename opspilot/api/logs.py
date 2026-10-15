from __future__ import annotations

from flask import current_app, jsonify, request

from opspilot.analyzer.ingest import analyze_logs
from opspilot.api import api_bp, int_arg
from opspilot.app import get_engine
from opspilot.errors import ValidationError
from opspilot.store import ingests

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def read_log_payload() -> tuple[list[str], str]:
    """Accept a multipart file upload, a JSON {"lines": [...]} body, or raw text."""
    if "file" in request.files:
        upload = request.files["file"]
        raw = upload.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValidationError("log file larger than 10 MB")
        return raw.decode("utf-8", errors="replace").splitlines(), upload.filename or "upload"
    if request.is_json:
        data = request.get_json(silent=True) or {}
        lines = data.get("lines")
        if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
            raise ValidationError("lines must be a list of strings")
        return lines, str(data.get("source") or "api")
    text = request.get_data(as_text=True)
    if not text.strip():
        raise ValidationError("no log data supplied")
    return text.splitlines(), request.args.get("source", "api")


@api_bp.post("/logs/analyze")
def analyze():
    lines, source = read_log_payload()
    cfg = current_app.config
    window = int_arg("window_seconds", cfg["SPIKE_WINDOW_SECONDS"], minimum=1, maximum=3600)
    threshold = int_arg("threshold", cfg["SPIKE_THRESHOLD"], minimum=1, maximum=100_000)
    with get_engine().begin() as conn:
        result = analyze_logs(
            conn, lines, source=source, window_seconds=window, threshold=threshold
        )
    return jsonify(result.as_dict()), 201


@api_bp.get("/logs/ingests")
def recent_ingests():
    with get_engine().connect() as conn:
        return jsonify(
            ingests=ingests.recent(conn, limit=int_arg("limit", 10, minimum=1, maximum=100))
        )
