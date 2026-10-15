from pathlib import Path

from opspilot import reports
from opspilot.seed import seed_demo
from opspilot.timeutil import utcnow

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"


def test_demo_seed_populates_reports_and_is_idempotent(engine):
    assert seed_demo(engine, RUNBOOK_DIR, days=4).startswith("seeded")
    assert "skipped" in seed_demo(engine, RUNBOOK_DIR, days=4)
    with engine.connect() as conn:
        assert reports.status_overview(conn)
        acceptance = reports.ai_acceptance(conn, since=utcnow().replace(year=2000))
    assert acceptance["overall"]["total"] > 0
