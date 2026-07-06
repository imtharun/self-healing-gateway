# built-in
import time
from datetime import timedelta

# third-party
import pytest

# local
from gateway.failure_detector import FailureDetector
from gateway.resilience.circuit_breaker import CircuitBreaker, CircuitStatus
from gateway.time_utils import now_ist


class FakeHealthMonitor:
    def __init__(self, health_status):
        self.health_status = health_status


@pytest.mark.asyncio
async def test_steady_healthy_upstream_moves_open_circuit_to_half_open_after_timeout(
    monkeypatch,
):
    upstream_url = "http://upstream.local"
    cb = CircuitBreaker(name="upstream", failure_threshold=1, recovery_timeout=1)
    cb.record_failure()
    cb.opened_at = time.time() - 2
    events = []

    async def fake_record_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr("gateway.failure_detector.record_event", fake_record_event)

    detector = FailureDetector(
        health_monitor=FakeHealthMonitor({upstream_url: True}),
        cb_registry={upstream_url: cb},
    )
    detector.previous_status = {upstream_url: True}

    await detector.check_once()

    assert cb.current_state == CircuitStatus.half_open
    assert events[0]["event_type"] == "circuit_half_open"


@pytest.mark.asyncio
async def test_unhealthy_upstream_records_periodic_still_unhealthy_event(monkeypatch):
    upstream_url = "http://upstream.local"
    cb = CircuitBreaker(name="upstream", failure_threshold=1, recovery_timeout=1)
    cb.record_failure()
    events = []

    async def fake_record_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr("gateway.failure_detector.record_event", fake_record_event)

    detector = FailureDetector(
        health_monitor=FakeHealthMonitor({upstream_url: False}),
        cb_registry={upstream_url: cb},
        unhealthy_event_interval=60,
    )
    detector.previous_status = {upstream_url: False}
    detector.last_unhealthy_event_at[upstream_url] = now_ist() - timedelta(
        seconds=61
    )

    await detector.check_once()

    assert events[0]["event_type"] == "health_still_unhealthy"
    assert events[0]["upstream_url"] == upstream_url
    assert events[0]["metadata"] == {"circuit_state": "OPEN"}


@pytest.mark.asyncio
async def test_unhealthy_upstream_suppresses_still_unhealthy_event_until_due(
    monkeypatch,
):
    upstream_url = "http://upstream.local"
    cb = CircuitBreaker(name="upstream", failure_threshold=1, recovery_timeout=1)
    cb.record_failure()
    events = []

    async def fake_record_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr("gateway.failure_detector.record_event", fake_record_event)

    detector = FailureDetector(
        health_monitor=FakeHealthMonitor({upstream_url: False}),
        cb_registry={upstream_url: cb},
        unhealthy_event_interval=60,
    )
    detector.previous_status = {upstream_url: False}
    detector.last_unhealthy_event_at[upstream_url] = now_ist()

    await detector.check_once()

    assert events == []
