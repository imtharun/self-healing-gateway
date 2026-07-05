# built-in
import time

# local
from gateway.resilience.circuit_breaker import CircuitBreaker, CircuitStatus


def test_circuit_breaker_moves_to_half_open_after_timeout():
    cb = CircuitBreaker(name="payments", failure_threshold=1, recovery_timeout=1)

    cb.record_failure()
    cb.opened_at = time.time() - 2

    assert cb.current_state == CircuitStatus.half_open
    assert cb.is_open() is False
    assert cb.state == CircuitStatus.half_open
