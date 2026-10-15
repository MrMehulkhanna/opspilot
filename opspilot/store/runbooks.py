from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from opspilot.db import fetch_all, fetch_one, insert_returning_id
from opspilot.timeutil import utcnow


def upsert(conn: Connection, slug: str, title: str, body: str, service_tag: str | None) -> int:
    existing = fetch_one(conn, "SELECT id FROM runbooks WHERE slug = :slug", slug=slug)
    if existing:
        conn.execute(
            text(
                "UPDATE runbooks SET title = :title, body = :body, service_tag = :tag,"
                " updated_at = :now WHERE id = :id"
            ),
            {
                "title": title,
                "body": body,
                "tag": service_tag,
                "now": utcnow(),
                "id": existing["id"],
            },
        )
        return existing["id"]
    return insert_returning_id(
        conn,
        "INSERT INTO runbooks (slug, title, service_tag, body, updated_at)"
        " VALUES (:slug, :title, :tag, :body, :now)",
        slug=slug,
        title=title,
        tag=service_tag,
        body=body,
        now=utcnow(),
    )


def list_all(conn: Connection) -> list[dict]:
    return fetch_all(conn, "SELECT * FROM runbooks ORDER BY title")


def get(conn: Connection, runbook_id: int) -> dict | None:
    return fetch_one(conn, "SELECT * FROM runbooks WHERE id = :id", id=runbook_id)
