"""Server-rendered dashboard for support engineers."""

from __future__ import annotations

import secrets

from flask import Blueprint, abort, request, session

web_bp = Blueprint(
    "web", __name__, template_folder="../templates", static_folder="../static", static_url_path="/static"
)


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@web_bp.before_request
def _check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "invalid or missing CSRF token")


@web_bp.app_context_processor
def _inject():
    return {"csrf_token": csrf_token, "current_engineer_id": session.get("engineer_id")}


from opspilot.web import views  # noqa: E402,F401
