"""Parse application log lines into structured records.

Two formats are accepted, so the analyzer works with both legacy text logs
and structured JSON logs:

    2026-10-01T09:00:01Z ERROR payments-api Timeout talking to ledger-db
    {"ts": "2026-10-01T09:00:01Z", "level": "error", "service": "payments-api", "msg": "..."}
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

from opspilot.timeutil import parse_timestamp

ERROR_LEVELS = frozenset({"ERROR", "CRITICAL", "FATAL"})
_LEVEL_ALIASES = {"WARNING": "WARN", "ERR": "ERROR", "CRIT": "CRITICAL"}

_TEXT_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
    r"\[?(?P<level>[A-Za-z]+)\]?\s+"
    r"(?P<service>[A-Za-z0-9_.\-]+):?\s+"
    r"(?P<message>.*)$"
)


@dataclass(frozen=True)
class LogRecord:
    timestamp: datetime
    level: str
    service: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.level in ERROR_LEVELS


def _normalize_level(level: str) -> str:
    upper = level.strip().upper()
    return _LEVEL_ALIASES.get(upper, upper)


def parse_line(line: str) -> LogRecord | None:
    """Parse one line; return None for blank or unrecognised lines."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        return _parse_json(line)
    match = _TEXT_LINE.match(line)
    if not match:
        return None
    try:
        ts = parse_timestamp(match["ts"])
    except ValueError:
        return None
    return LogRecord(
        timestamp=ts,
        level=_normalize_level(match["level"]),
        service=match["service"].lower(),
        message=match["message"].strip(),
    )


def _parse_json(line: str) -> LogRecord | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    ts = data.get("ts") or data.get("timestamp") or data.get("time")
    level = data.get("level") or data.get("severity")
    service = data.get("service") or data.get("app")
    message = data.get("msg") or data.get("message") or ""
    if not (ts and level and service):
        return None
    try:
        timestamp = parse_timestamp(str(ts))
    except ValueError:
        return None
    return LogRecord(timestamp, _normalize_level(str(level)), str(service).lower(), str(message))


def parse_lines(lines: Iterable[str]) -> Iterator[LogRecord | None]:
    for line in lines:
        yield parse_line(line)
