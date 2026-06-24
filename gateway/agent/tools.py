# built-in
import time

# local
from gateway.resilience.circuit_breaker import CircuitStatus


def get_upstream_state(upstream_url: str, cb_registry, health_monitor) -> dict:
    """
    Returns current state of an upstream: CB state, health, failure count
    """
    cb = cb_registry[upstream_url]
    return {
        "upstream": upstream_url,
        "circuit_state": cb.state.value,
        "failure_count": cb.failure_count,
        "failure_threshold": cb.failure_threshold,
        "is_healthy": health_monitor.health_status.get(upstream_url),
    }


def open_circuit(upstream_url: str, cb_registry) -> dict:
    """
    Opens the circuit breaker for an upstream
    """
    cb = cb_registry[upstream_url]
    cb.state = CircuitStatus.open
    cb.opened_at = time.time()

    return {
        "status": "success",
        "upstream": upstream_url,
        "new_state": "open",
        "message": f"Circuit opened for {upstream_url}. Traffic is now blocked.",
    }


def close_circuit(upstream_url: str, cb_registry) -> dict:
    """
    Closes the circuit breaker and resets failure count
    """
    cb = cb_registry[upstream_url]
    cb.state = CircuitStatus.closed
    cb.failure_count = 0
    cb.opened_at = None

    return {
        "status": "success",
        "upstream": upstream_url,
        "new_state": "CLOSED",
        "message": f"Circuit closed for {upstream_url}. Traffic resumed.",
    }


def drain_upstream(upstream_url: str, cb_registry) -> dict:
    """
    Fully opens circuit + marks as drained (no auto-recovery)
    """
    cb = cb_registry[upstream_url]
    cb.state = CircuitStatus.open
    cb.opened_at = time.time()
    cb.failure_count = cb.failure_threshold + 1

    return {
        "status": "success",
        "upstream": upstream_url,
        "drained": True,
        "message": f"Circuit completely drained for {upstream_url}",
    }


def mark_resolved(upstream_url: str, reason: str) -> dict:
    """
    Signals the agent that healing is complete
    """
    return {
        "resolved": True,
        "upstream": upstream_url,
        "reason": reason,
        "message": "Healing session marked as resolved.",
    }
