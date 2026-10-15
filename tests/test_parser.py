from datetime import datetime

import pytest

from opspilot.analyzer.parser import parse_line


def test_parses_plain_text_line():
    rec = parse_line("2026-10-01T09:00:01Z ERROR payments-api Timeout talking to ledger-db")
    assert rec.timestamp == datetime(2026, 10, 1, 9, 0, 1)
    assert rec.level == "ERROR"
    assert rec.service == "payments-api"
    assert rec.message == "Timeout talking to ledger-db"
    assert rec.is_error


def test_parses_bracketed_level_and_colon_after_service():
    rec = parse_line("2026-10-01 09:00:01 [warning] Auth: token refresh slow")
    assert rec.level == "WARN"
    assert rec.service == "auth"
    assert not rec.is_error


def test_converts_offset_timestamps_to_utc():
    rec = parse_line("2026-10-01T14:30:00+05:30 ERROR search index unavailable")
    assert rec.timestamp == datetime(2026, 10, 1, 9, 0, 0)


def test_parses_json_line():
    rec = parse_line(
        '{"ts": "2026-10-01T09:00:01Z", "level": "critical", "service": "Orders",'
        ' "msg": "deadlock detected"}'
    )
    assert (rec.level, rec.service, rec.message) == ("CRITICAL", "orders", "deadlock detected")
    assert rec.is_error


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "not a log line at all",
        "{broken json",
        '{"level": "error", "service": "x"}',
        "2026-13-45T99:00:00Z ERROR svc bad date",
        "[1, 2, 3]",
    ],
)
def test_unparseable_lines_return_none(line):
    assert parse_line(line) is None
