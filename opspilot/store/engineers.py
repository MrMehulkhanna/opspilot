from __future__ import annotations

from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, fetch_one, insert_returning_id
from opspilot.timeutil import utcnow


def create(conn: Connection, name: str, email: str, role: str = "engineer") -> int:
    return insert_returning_id(
        conn,
        "INSERT INTO engineers (name, email, role, created_at) "
        "VALUES (:name, :email, :role, :created_at)",
        name=name,
        email=email.strip().lower(),
        role=role,
        created_at=utcnow(),
    )


def get(conn: Connection, engineer_id: int) -> dict | None:
    return fetch_one(conn, "SELECT * FROM engineers WHERE id = :id", id=engineer_id)


def get_by_email(conn: Connection, email: str) -> dict | None:
    return fetch_one(
        conn, "SELECT * FROM engineers WHERE email = :email", email=email.strip().lower()
    )


def list_all(conn: Connection) -> list[dict]:
    return fetch_all(conn, "SELECT * FROM engineers ORDER BY name")
