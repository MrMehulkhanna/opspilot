"""Shared fixtures.

Tests run against SQLite by default. Set TEST_DATABASE_URL to a PostgreSQL
URL to run the same suite against Postgres (CI does both).
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from opspilot.db import drop_all, init_schema, make_engine

T0 = datetime(2026, 10, 1, 9, 0, 0)


@pytest.fixture
def db_url(tmp_path):
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def engine(db_url):
    eng = make_engine(db_url)
    drop_all(eng)
    init_schema(eng)
    yield eng
    drop_all(eng)
    eng.dispose()
