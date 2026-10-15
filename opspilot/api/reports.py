from __future__ import annotations

from datetime import timedelta

from flask import jsonify

from opspilot import reports
from opspilot.api import api_bp, int_arg
from opspilot.app import get_engine
from opspilot.timeutil import utcnow


def _since():
    return utcnow() - timedelta(days=int_arg("days", 30, minimum=1, maximum=365))


@api_bp.get("/reports/sla-breaches")
def sla_breaches():
    with get_engine().connect() as conn:
        return jsonify(rows=reports.sla_breaches(conn, since=_since(), now=utcnow()))


@api_bp.get("/reports/mttr")
def mttr():
    with get_engine().connect() as conn:
        return jsonify(rows=reports.mean_time_to_resolve(conn, since=_since()))


@api_bp.get("/reports/ai-acceptance")
def ai_acceptance():
    with get_engine().connect() as conn:
        return jsonify(reports.ai_acceptance(conn, since=_since()))


@api_bp.get("/reports/runbooks")
def runbook_usefulness():
    with get_engine().connect() as conn:
        return jsonify(rows=reports.runbook_usefulness(conn, since=_since()))
