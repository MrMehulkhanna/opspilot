"""Sliding-window error spike detection.

For each service we keep a deque of the timestamps of its recent error lines.
Old entries fall off the left as time moves forward, so the deque length is
always "errors in the last W seconds". When it reaches the threshold a spike
episode starts. The episode only ends once the rate falls to half the
threshold (hysteresis), so a rate hovering around the threshold is reported
as one episode instead of flapping into many. Each episode is reported once,
with its peak rate and the most common error.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from opspilot.analyzer.parser import LogRecord


@dataclass
class Spike:
    service: str
    started_at: datetime
    ended_at: datetime
    peak_errors_in_window: int
    total_errors: int
    messages: Counter = field(default_factory=Counter)

    @property
    def top_message(self) -> str:
        return self.messages.most_common(1)[0][0] if self.messages else ""


@dataclass
class _ServiceWindow:
    times: deque = field(default_factory=deque)
    active: Spike | None = None


class SpikeDetector:
    def __init__(self, window_seconds: int = 60, threshold: int = 10):
        if window_seconds <= 0 or threshold <= 0:
            raise ValueError("window_seconds and threshold must be positive")
        self.window = timedelta(seconds=window_seconds)
        self.threshold = threshold
        self.clear_below = max(1, threshold // 2)
        self._services: dict[str, _ServiceWindow] = {}
        self._finished: list[Spike] = []

    def observe(self, record: LogRecord) -> None:
        if not record.is_error:
            return
        state = self._services.setdefault(record.service, _ServiceWindow())
        now = record.timestamp
        times = state.times
        times.append(now)
        while times and now - times[0] >= self.window:
            times.popleft()

        if state.active is not None:
            if len(times) < self.clear_below:
                self._finished.append(state.active)
                state.active = None
            else:
                spike = state.active
                spike.ended_at = now
                spike.total_errors += 1
                spike.peak_errors_in_window = max(spike.peak_errors_in_window, len(times))
                spike.messages[record.message] += 1
                return

        if len(times) >= self.threshold:
            state.active = Spike(
                service=record.service,
                started_at=times[0],
                ended_at=now,
                peak_errors_in_window=len(times),
                total_errors=len(times),
                messages=Counter({record.message: 1}),
            )

    def finish(self) -> list[Spike]:
        """Close any open episodes and return every spike seen, oldest first."""
        for state in self._services.values():
            if state.active is not None:
                self._finished.append(state.active)
                state.active = None
        spikes, self._finished = self._finished, []
        return sorted(spikes, key=lambda s: (s.started_at, s.service))


def detect_spikes(
    records: Iterable[LogRecord], window_seconds: int = 60, threshold: int = 10
) -> list[Spike]:
    """Run detection over a batch. Records are sorted first, since log files
    merged from several hosts are rarely in perfect timestamp order."""
    detector = SpikeDetector(window_seconds, threshold)
    for record in sorted(records, key=lambda r: r.timestamp):
        detector.observe(record)
    return detector.finish()


def severity_for(spike: Spike, threshold: int) -> str:
    """Grade a spike by how far its peak rate overshot the threshold."""
    ratio = spike.peak_errors_in_window / threshold
    if ratio >= 4:
        return "SEV1"
    if ratio >= 2:
        return "SEV2"
    return "SEV3"
