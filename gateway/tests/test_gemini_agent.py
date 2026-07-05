# third-party
import pytest

# local
from gateway.agent.gemini_agent import execute_tool, run_healing_session
from gateway.resilience.circuit_breaker import CircuitBreaker


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


def test_execute_tool_preserves_gemini_reason():
    result = execute_tool(
        "mark_resolved",
        {
            "upstream_url": "http://known.local",
            "reason": "Health checks failed, so the circuit was opened and traffic is blocked.",
            "suspected_cause": "Health endpoint failed",
            "action_taken": "Opened circuit",
            "operator_next_step": "Inspect service logs",
        },
        {"http://known.local": CircuitBreaker("known")},
        health_monitor=None,
    )

    assert result["reason"] == (
        "Health checks failed, so the circuit was opened and traffic is blocked."
    )
    assert result["suspected_cause"] == "Health endpoint failed"
    assert result["action_taken"] == "Opened circuit"
    assert result["operator_next_step"] == "Inspect service logs"
