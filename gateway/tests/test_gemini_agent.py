# third-party
import pytest

# local
from gateway.agent.gemini_agent import execute_tool, run_healing_session
from gateway.resilience.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_execute_tool_rejects_unknown_upstream():
    with pytest.raises(ValueError, match="not registered"):
        await execute_tool(
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


@pytest.mark.asyncio
async def test_execute_tool_preserves_gemini_reason():
    result = await execute_tool(
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


@pytest.mark.asyncio
async def test_high_impact_tool_requests_human_approval(monkeypatch):
    requests = []

    async def fake_request_approval(**kwargs):
        requests.append(kwargs)
        return {"status": "pending_approval", "approval_id": "approval-1"}

    monkeypatch.setattr(
        "gateway.agent.gemini_agent.request_approval", fake_request_approval
    )
    result = await execute_tool(
        "drain_upstream",
        {"upstream_url": "http://known.local", "reason": "Repeated failures"},
        {"http://known.local": CircuitBreaker("known")},
        health_monitor=None,
    )

    assert result["status"] == "pending_approval"
    assert requests[0]["action"] == "drain_upstream"
