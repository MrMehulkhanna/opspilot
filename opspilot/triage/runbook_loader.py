"""Load runbooks from Markdown files with a small front-matter header.

---
title: Database connection pool exhausted
service: orders-db
---
body...
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Connection

from opspilot.store import runbooks


def parse_runbook(text: str) -> tuple[dict, str]:
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        _, header, body = text.split("---", 2)
        for line in header.strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip().lower()] = value.strip()
    return meta, body.strip()


def load_directory(conn: Connection, directory: Path) -> int:
    count = 0
    for path in sorted(Path(directory).glob("*.md")):
        meta, body = parse_runbook(path.read_text(encoding="utf-8"))
        runbooks.upsert(
            conn,
            slug=path.stem,
            title=meta.get("title", path.stem.replace("-", " ").title()),
            body=body,
            service_tag=meta.get("service") or None,
        )
        count += 1
    return count
