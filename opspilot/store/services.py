from __future__ import annotations

from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, fetch_one, insert_returning_id
from opspilot.timeutil import utcnow


def get_by_name(conn: Connection, name: str) -> dict | None:
    return fetch_one(conn, "SELECT * FROM services WHERE name = :name", name=name)


def get(conn: Connection, service_id: int) -> dict | None:
    return fetch_one(conn, "SELECT * FROM services WHERE id = :id", id=service_id)


def list_all(conn: Connection) -> list[dict]:
    return fetch_all(conn, "SELECT * FROM services ORDER BY name")


def create(conn: Connection, name: str, team: str = "unassigned", tier: int = 2) -> int:
    return insert_returning_id(
        conn,
        "INSERT INTO services (name, team, tier, created_at) "
        "VALUES (:name, :team, :tier, :created_at)",
        name=name,
        team=team,
        tier=tier,
        created_at=utcnow(),
    )


def get_or_create(conn: Connection, name: str) -> dict:
    """Services are discovered from logs, so unknown names are registered on sight."""
    existing = get_by_name(conn, name)
    if existing:
        return existing
    create(conn, name)
    return get_by_name(conn, name)
