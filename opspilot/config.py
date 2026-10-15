"""Runtime configuration, read from environment variables.

Everything has a sensible default so the app runs out of the box against a
local SQLite file; production deployments point DATABASE_URL at PostgreSQL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass
class Config:
    DATABASE_URL: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///opspilot.db")
    )
    SECRET_KEY: str = field(
        default_factory=lambda: os.environ.get("SECRET_KEY", "dev-only-change-me")
    )
    # Optional shared key for the REST API. Empty = API is open (local dev).
    API_KEY: str = field(default_factory=lambda: os.environ.get("OPSPILOT_API_KEY", ""))

    # Log analyzer: open an incident when a service logs at least
    # SPIKE_THRESHOLD errors inside any SPIKE_WINDOW_SECONDS sliding window.
    SPIKE_WINDOW_SECONDS: int = field(
        default_factory=lambda: _env_int("OPSPILOT_SPIKE_WINDOW_SECONDS", 60)
    )
    SPIKE_THRESHOLD: int = field(default_factory=lambda: _env_int("OPSPILOT_SPIKE_THRESHOLD", 10))

    # LLM triage. Without a key the rule-based triager is used.
    LLM_API_KEY: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    LLM_MODEL: str = field(
        default_factory=lambda: os.environ.get("OPSPILOT_LLM_MODEL", "claude-haiku-5-5")
    )
    LLM_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: _env_int("OPSPILOT_LLM_TIMEOUT_SECONDS", 20)
    )
    RUNBOOK_TOP_K: int = field(default_factory=lambda: _env_int("OPSPILOT_RUNBOOK_TOP_K", 3))

    TESTING: bool = False

    def as_flask_config(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
