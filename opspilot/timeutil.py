"""UTC time helpers. All timestamps in OpsPilot are naive UTC datetimes."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def to_datetime(value) -> datetime | None:
    """Normalise a DB value to a naive UTC datetime.

    PostgreSQL returns datetime objects; SQLite hands back ISO strings.
    """
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).replace("T", " ").rstrip("Z")
    return datetime.fromisoformat(text)


def parse_timestamp(text: str) -> datetime:
    """Parse an ISO-8601 timestamp from a log line into naive UTC."""
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt
