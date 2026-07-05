# third-party
import pytest

# local
from gateway.agent.gemini_agent import execute_tool, run_healing_session
from gateway.agent.gemini_agent import _build_detailed_reason
from gateway.resilience.circuit_breaker import CircuitBreaker


class FakeHealthMonitor:
    health_status = {"http://known.local": False}


def test_execute_tool_rejects_unknown_upstream():
    with pytest.raises(ValueError, match="not registered"):
        execute_tool(
            "open_circuit",
            {"upstream_url": "http://unknown.local"},
            {"http://known.local": CircuitBreaker("known")},
            health_monitor=None,
        )


@pytest.mark.asyncio
async def test_run_healing_session_skips_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = await run_healing_session(
        upstream_url="http://known.local",
        context="failure",
        cb_registry={"http://known.local": CircuitBreaker("known")},
        health_monitor=None,
    )

    assert result["status"] == "skipped"
    assert result["actions_taken"] == []


def test_build_detailed_reason_replaces_vague_agent_reason():
    cb = CircuitBreaker("known", failure_threshold=5)
    cb.record_failure()

    reason = _build_detailed_reason(
        upstream_url="http://known.local",
        cb_registry={"http://known.local": cb},
        health_monitor=FakeHealthMonitor(),
        actions_taken=["get_upstream_state", "open_circuit", "mark_resolved"],
        agent_reason="Circuit opened to prevent cascading failures.",
    )

    assert reason == "Unhealthy upstream; circuit CLOSED after mark_resolved (1/5 failures)."
    assert "prevent cascading failures" not in reason
