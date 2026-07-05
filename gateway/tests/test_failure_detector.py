# built-in
import time

# third-party
import pytest

# local
from gateway.failure_detector import FailureDetector
from gateway.resilience.circuit_breaker import CircuitBreaker, CircuitStatus


class FakeHealthMonitor:
    def __init__(self, health_status):
        self.health_status = health_status


@pytest.mark.asyncio
async def test_steady_healthy_upstream_moves_open_circuit_to_half_open_after_timeout():
    upstream_url = "http://upstream.local"
    cb = CircuitBreaker(name="upstream", failure_threshold=1, recovery_timeout=1)
    cb.record_failure()
    cb.opened_at = time.time() - 2

    detector = FailureDetector(
        health_monitor=FakeHealthMonitor({upstream_url: True}),
        cb_registry={upstream_url: cb},
    )
    detector.previous_status = {upstream_url: True}

    await detector.check_once()

    assert cb.current_state == CircuitStatus.half_open
