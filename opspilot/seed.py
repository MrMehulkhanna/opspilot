"""Demo data: two weeks of incidents with realistic handling, for the dashboard.

Logs are generated per day and run through the real analyzer, then each
incident is acknowledged, investigated and resolved at plausible (sometimes
SLA-breaching) times, and its AI suggestion is reviewed by an engineer.
"""

from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

from sqlalchemy.engine import Engine

from opspilot import incidents
from opspilot.analyzer.ingest import analyze_logs
from opspilot.loggen import Burst, generate
from opspilot.store import engineers
from opspilot.store import incidents as incident_store
from opspilot.timeutil import utcnow
from opspilot.triage.engine import review, suggest
from opspilot.triage.runbook_loader import load_directory

ENGINEERS = (
    ("Asha Rao", "asha.rao@example.com", "lead"),
    ("Ravi Menon", "ravi.menon@example.com", "engineer"),
    ("Neha Iyer", "neha.iyer@example.com", "engineer"),
)

BURST_TEMPLATES = (
    ("payments-api", 0.6, "gateway timeout: upstream payment provider timed out after 30s"),
    ("orders-db", 0.35, "timeout acquiring connection: connection pool exhausted"),
    ("auth", 0.3, "jwt signature verification failed: unknown key id"),
    ("search", 0.3, "statement timeout: slow query on products index"),
    ("notifications", 0.25, "consumer lag growing: message processing timeout"),
    ("orders-db", 0.4, "could not write to WAL: no space left on device"),
)


def seed_demo(engine: Engine, runbook_dir: Path, days: int = 14, seed: int = 42) -> str:
    rng = random.Random(seed)
    with engine.begin() as conn:
        load_directory(conn, runbook_dir)
        team = []
        for name, email, role in ENGINEERS:
            existing = engineers.get_by_email(conn, email)
            team.append(existing["id"] if existing else engineers.create(conn, name, email, role))

    opened = 0
    today = utcnow().replace(hour=0, minute=0, second=0)
    for day in range(days, 0, -1):
        start = today - timedelta(days=day) + timedelta(hours=8)
        picks = rng.sample(BURST_TEMPLATES, k=rng.randint(1, 3))
        bursts = [
            Burst(
                svc,
                start + timedelta(minutes=rng.randint(10, 90)),
                rng.randint(90, 300),
                rate * rng.uniform(0.3, 1.4),
                msg,
            )
            for svc, rate, msg in picks
        ]
        lines = generate(start, minutes=120, bursts=bursts, seed=rng.randint(0, 10_000))
        with engine.begin() as conn:
            result = analyze_logs(conn, lines, source=f"demo-day-{day}.log")
            for incident_id in result.opened:
                _handle(conn, incident_id, rng, team, final=day > 2)
                opened += 1
    return f"seeded {opened} incidents over {days} days with {len(team)} engineers"


def _handle(conn, incident_id: int, rng: random.Random, team: list[int], final: bool) -> None:
    incident = incident_store.get(conn, incident_id)
    engineer = rng.choice(team)
    at = incident["opened_at"]

    suggestion = suggest(conn, incident_id)
    if not final and rng.random() < 0.5:
        return  # leave some incidents open for the live dashboard

    at += timedelta(minutes=rng.choice([4, 8, 12, 25, 50]))
    incidents.transition(conn, incident_id, "acknowledged", actor_id=engineer, at=at)

    roll = rng.random()
    if roll < 0.6:
        review(conn, suggestion["id"], decision="approve", reviewer_id=engineer)
    elif roll < 0.85:
        steps = suggestion["suggested_steps"][:2] + ["Confirm error rate is back to baseline"]
        review(conn, suggestion["id"], decision="edit", reviewer_id=engineer, edited_steps=steps)
    else:
        review(conn, suggestion["id"], decision="reject", reviewer_id=engineer,
               comment="Cause was a config change, not covered by the runbook")

    at += timedelta(minutes=rng.randint(5, 30))
    incidents.transition(conn, incident_id, "investigating", actor_id=engineer, at=at)
    if not final and rng.random() < 0.5:
        return
    at += timedelta(minutes=rng.choice([20, 45, 90, 180, 420, 900]))
    incidents.transition(
        conn, incident_id, "resolved", actor_id=engineer, at=at,
        note="Applied runbook steps; error rate back to baseline",
    )
    if rng.random() < 0.7:
        incidents.transition(conn, incident_id, "closed", actor_id=engineer, at=at + timedelta(hours=1))
