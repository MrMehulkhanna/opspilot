from datetime import datetime, timedelta

import pytest

from opspilot.analyzer.parser import LogRecord
from opspilot.analyzer.window import SpikeDetector, detect_spikes, severity_for

T0 = datetime(2026, 10, 1, 9, 0, 0)


def errors(service, count, start=T0, every=1.0, msg="boom", level="ERROR"):
    return [
        LogRecord(start + timedelta(seconds=i * every), level, service, msg) for i in range(count)
    ]


def test_no_spike_below_threshold():
    assert detect_spikes(errors("api", 9), window_seconds=60, threshold=10) == []


def test_spike_at_threshold():
    spikes = detect_spikes(errors("api", 10), window_seconds=60, threshold=10)
    assert len(spikes) == 1
    assert spikes[0].service == "api"
    assert spikes[0].started_at == T0


def test_errors_spread_beyond_window_do_not_spike():
    # 20 errors, one every 10s -> at most 6 inside any 60s window
    assert detect_spikes(errors("api", 20, every=10), window_seconds=60, threshold=10) == []


def test_non_error_levels_ignored():
    assert detect_spikes(errors("api", 50, level="WARN"), 60, 10) == []


def test_sustained_spike_is_one_episode_with_peak():
    spikes = detect_spikes(errors("api", 40, every=0.5), window_seconds=60, threshold=10)
    assert len(spikes) == 1
    assert spikes[0].peak_errors_in_window == 40
    assert spikes[0].total_errors == 40


def test_two_bursts_separated_by_quiet_period_are_two_episodes():
    first = errors("api", 12)
    second = errors("api", 12, start=T0 + timedelta(minutes=30))
    spikes = detect_spikes(first + second, window_seconds=60, threshold=10)
    assert len(spikes) == 2


def test_rate_hovering_near_threshold_does_not_flap():
    # ~1 error every 5.5s keeps the 60s window at 10-11 errors, then dips to 9-10
    recs = errors("api", 60, every=5.5)
    assert len(detect_spikes(recs, window_seconds=60, threshold=10)) == 1


def test_services_are_tracked_independently():
    recs = errors("api", 6) + errors("db", 6)
    assert detect_spikes(recs, 60, 10) == []
    recs = errors("api", 10) + errors("db", 12, msg="conn refused")
    services = {s.service: s for s in detect_spikes(recs, 60, 10)}
    assert set(services) == {"api", "db"}
    assert services["db"].top_message == "conn refused"


def test_out_of_order_records_are_sorted():
    recs = list(reversed(errors("api", 10)))
    assert len(detect_spikes(recs, 60, 10)) == 1


def test_invalid_detector_config():
    with pytest.raises(ValueError):
        SpikeDetector(window_seconds=0, threshold=5)


@pytest.mark.parametrize(("peak", "expected"), [(10, "SEV3"), (25, "SEV2"), (45, "SEV1")])
def test_severity_scales_with_overshoot(peak, expected):
    spike = detect_spikes(errors("api", peak, every=0.1), 60, 10)[0]
    assert severity_for(spike, threshold=10) == expected
