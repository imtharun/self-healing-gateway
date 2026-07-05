# built-in
import time

# local
from gateway.resilience.circuit_breaker import CircuitBreaker, CircuitStatus


def test_circuit_breaker_stays_open_after_timeout_until_recovery_is_allowed():
    cb = CircuitBreaker(name="payments", failure_threshold=1, recovery_timeout=1)

    cb.record_failure()
    cb.opened_at = time.time() - 2

    assert cb.current_state == CircuitStatus.open
    assert cb.can_try_recovery() is True
    assert cb.is_open() is True


def test_circuit_breaker_can_be_marked_half_open_for_trial_traffic():
    cb = CircuitBreaker(name="payments", failure_threshold=1, recovery_timeout=1)

    cb.record_failure()
    cb.opened_at = time.time() - 2
    cb.mark_half_open()

    assert cb.current_state == CircuitStatus.half_open
    assert cb.is_open() is False


def test_circuit_breaker_success_closes_half_open_circuit():
    cb = CircuitBreaker(name="payments", failure_threshold=1, recovery_timeout=1)

    cb.record_failure()
    cb.opened_at = time.time() - 2
    cb.mark_half_open()
    cb.record_success()

    assert cb.current_state == CircuitStatus.closed
    assert cb.failure_count == 0
