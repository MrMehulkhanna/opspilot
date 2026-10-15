"""REST API, mounted at /api/v1."""

from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request

from opspilot.errors import OpsPilotError, ValidationError

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.before_request
def _require_api_key():
    expected = current_app.config.get("API_KEY")
    if not expected or request.endpoint == "api.health":
        return None
    supplied = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        return jsonify(error="missing or invalid API key"), 401
    return None


@api_bp.errorhandler(OpsPilotError)
def _domain_error(exc: OpsPilotError):
    return jsonify(error=str(exc)), exc.status_code


@api_bp.errorhandler(404)
def _not_found(_exc):
    return jsonify(error="not found"), 404


@api_bp.errorhandler(405)
def _method_not_allowed(_exc):
    return jsonify(error="method not allowed"), 405


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    return data


def actor_id() -> int | None:
    """The engineer performing the action, from the X-Engineer-Id header."""
    raw = request.headers.get("X-Engineer-Id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError("X-Engineer-Id must be an integer") from exc


def require_actor() -> int:
    actor = actor_id()
    if actor is None:
        raise ValidationError("X-Engineer-Id header is required for this action")
    return actor


def int_arg(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{name} out of range")
    return value


from opspilot.api import incidents, logs, misc, reports  # noqa: E402,F401
