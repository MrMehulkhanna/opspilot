"""Synthetic log generator for demos and load testing.

Produces background traffic for several services plus injected error bursts,
so the analyzer has something realistic to find. Seeded for reproducibility.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

SERVICES = ("payments-api", "orders-db", "auth", "search", "notifications")

INFO_MESSAGES = (
    "request completed in {ms}ms",
    "cache hit ratio {pct}%",
    "health check passed",
    "processed batch of {n} items",
)
WARN_MESSAGES = ("retrying request (attempt 2)", "slow response from upstream: {ms}ms")
BACKGROUND_ERRORS = ("unexpected EOF from client", "request validation failed")


@dataclass(frozen=True)
class Burst:
    service: str
    start: datetime
    seconds: int
    errors_per_second: float
    message: str


DEFAULT_BURSTS = (
    (
        "payments-api",
        45,
        180,
        0.6,
        "gateway timeout: upstream payment provider timed out after 30s",
    ),
    ("orders-db", 120, 240, 0.35, "timeout acquiring connection: connection pool exhausted"),
    ("auth", 200, 90, 0.25, "jwt signature verification failed: unknown key id"),
    ("notifications", 300, 300, 0.12, "consumer lag growing: message processing timeout"),
)


def default_bursts(start: datetime) -> list[Burst]:
    return [
        Burst(svc, start + timedelta(minutes=offset), secs, rate, msg)
        for svc, offset, secs, rate, msg in DEFAULT_BURSTS
    ]


def _fill(template: str, rng: random.Random) -> str:
    return template.format(ms=rng.randint(5, 900), pct=rng.randint(60, 99), n=rng.randint(10, 500))


def generate(
    start: datetime,
    minutes: int = 360,
    bursts: list[Burst] | None = None,
    seed: int = 7,
    json_ratio: float = 0.2,
) -> list[str]:
    rng = random.Random(seed)
    bursts = default_bursts(start) if bursts is None else bursts
    events: list[tuple[datetime, str, str, str]] = []

    for second in range(0, minutes * 60, 2):
        ts = start + timedelta(seconds=second)
        service = rng.choice(SERVICES)
        roll = rng.random()
        if roll < 0.02:
            events.append((ts, "ERROR", service, rng.choice(BACKGROUND_ERRORS)))
        elif roll < 0.08:
            events.append((ts, "WARN", service, _fill(rng.choice(WARN_MESSAGES), rng)))
        else:
            events.append((ts, "INFO", service, _fill(rng.choice(INFO_MESSAGES), rng)))

    for burst in bursts:
        for second in range(burst.seconds):
            hits = int(burst.errors_per_second) + (rng.random() < burst.errors_per_second % 1)
            for _ in range(hits):
                ts = burst.start + timedelta(seconds=second, milliseconds=rng.randint(0, 999))
                events.append((ts, "ERROR", burst.service, burst.message))

    events.sort(key=lambda e: e[0])
    lines = []
    for ts, level, service, message in events:
        stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
        if rng.random() < json_ratio:
            lines.append(
                json.dumps(
                    {"ts": stamp, "level": level.lower(), "service": service, "msg": message}
                )
            )
        else:
            lines.append(f"{stamp} {level} {service} {message}")
    return lines
