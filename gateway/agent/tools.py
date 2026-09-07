# built-in
import os
import time

# third-party
import httpx

# local
from gateway.audit.store import get_events
from gateway.resilience.circuit_breaker import CircuitStatus


def open_circuit(upstream_url: str, cb_registry) -> dict:
    """
    Opens the circuit breaker for an upstream
    """
    cb = cb_registry[upstream_url]
    cb.state = CircuitStatus.open
    cb.opened_at = time.time()

    return {
        "status": "success",
        "upstream_url": upstream_url,
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
        "upstream_url": upstream_url,
        "new_state": "CLOSED",
        "message": f"Circuit closed for {upstream_url}. Traffic resumed.",
    }


def get_upstream_state(upstream_url: str, cb_registry, health_monitor) -> dict:
    """
    Returns current state of an upstream: CB state, health, failure count
    """
    cb = cb_registry[upstream_url]
    return {
        "upstream_url": upstream_url,
        "circuit_state": cb.state.value,
        "failure_count": cb.failure_count,
        "failure_threshold": cb.failure_threshold,
        "is_healthy": health_monitor.health_status.get(upstream_url),
    }


async def get_recent_events(upstream_url: str, limit: int = 10) -> dict:
    """
    Returns recent audit events for incident memory.
    """
    events = await get_events(limit=limit, upstream_url=upstream_url)
    return {
        "upstream_url": upstream_url,
        "events": [
            {
                "event_type": event["event_type"],
                "occurred_at": event["occurred_at"],
                "message": event["message"],
                "metadata": event["metadata"],
            }
            for event in events
        ],
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
        "upstream_url": upstream_url,
        "drained": True,
        "message": f"Circuit completely drained for {upstream_url}",
    }


def mark_resolved(
    upstream_url: str,
    reason: str,
    suspected_cause: str | None = None,
    action_taken: str | None = None,
    operator_next_step: str | None = None,
) -> dict:
    """
    Signals the agent that healing is complete
    """
    return {
        "status": "resolved",
        "resolved": True,
        "upstream_url": upstream_url,
        "reason": reason,
        "suspected_cause": suspected_cause,
        "action_taken": action_taken,
        "operator_next_step": operator_next_step,
        "message": "Healing session marked as resolved.",
    }


async def create_incident_ticket(
    upstream_url: str,
    reason: str,
    severity: str = "high",
) -> dict:
    webhook_url = os.getenv("INCIDENT_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("INCIDENT_WEBHOOK_URL is not configured")

    headers = {"Content-Type": "application/json"}
    webhook_token = os.getenv("INCIDENT_WEBHOOK_TOKEN")
    if webhook_token:
        headers["Authorization"] = f"Bearer {webhook_token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            webhook_url,
            headers=headers,
            json={
                "title": f"Gateway incident: {upstream_url}",
                "upstream_url": upstream_url,
                "reason": reason,
                "severity": severity,
                "source": "self-healing-gateway",
            },
        )
        response.raise_for_status()
    return {
        "status": "success",
        "upstream_url": upstream_url,
        "message": "Incident webhook accepted the ticket request.",
        "response_status": response.status_code,
    }
