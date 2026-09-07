# built-in
from datetime import datetime

# third-party
import pytest

from gateway.audit import store
from gateway.audit.models import HealingSession, RemediationApproval
from gateway.upstreams.models import ManagedUpstream


@pytest.mark.asyncio
async def test_save_and_get_sessions_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "audit.db")
    await store.init_db()

    session = HealingSession(
        session_id="session-1",
        upstream_url="https://payments.example.com",
        triggered_at=datetime(2026, 1, 1, 10, 0, 0),
        resolved_at=datetime(2026, 1, 1, 10, 0, 5),
        status="resolved",
        reason="Circuit opened",
        suspected_cause="Health check failed",
        action_taken="Opened circuit",
        operator_next_step="Inspect upstream logs",
        actions_taken=["get_upstream_state", "open_circuit"],
    )

    await store.save_session(session)
    sessions = await store.get_sessions()

    assert sessions[0]["session_id"] == "session-1"
    assert sessions[0]["actions_taken"] == [
        "get_upstream_state",
        "open_circuit",
    ]
    assert sessions[0]["suspected_cause"] == "Health check failed"
    assert sessions[0]["action_taken"] == "Opened circuit"
    assert sessions[0]["operator_next_step"] == "Inspect upstream logs"


@pytest.mark.asyncio
async def test_record_and_get_events_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "audit.db")
    await store.init_db()

    await store.record_event(
        event_type="circuit_closed",
        upstream_url="https://payments.example.com",
        message="Circuit closed after trial request.",
        metadata={"status_code": 200},
    )
    await store.record_event(
        event_type="health_failed",
        upstream_url="https://orders.example.com",
        message="Other upstream failed.",
    )

    events = await store.get_events(upstream_url="https://payments.example.com")

    assert len(events) == 1
    assert events[0]["event_type"] == "circuit_closed"
    assert events[0]["upstream_url"] == "https://payments.example.com"
    assert events[0]["metadata"] == {"status_code": 200}


@pytest.mark.asyncio
async def test_managed_upstream_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "audit.db")
    await store.init_db()
    upstream = ManagedUpstream(
        upstream_id="upstream-1",
        name="inventory",
        path="/api/inventory",
        upstream_url="https://inventory.example.com",
        health_check="/health",
        failure_threshold=4,
        recovery_timeout=45,
    )

    await store.save_upstream(upstream)
    upstreams = await store.get_upstreams()

    assert upstreams[0]["upstream_id"] == "upstream-1"
    assert upstreams[0]["path"] == "/api/inventory"
    assert upstreams[0]["managed"] is True

    updated = upstream.model_copy(
        update={"name": "catalog", "path": "/api/catalog"}
    )
    await store.update_upstream(updated)
    upstreams = await store.get_upstreams()
    assert upstreams[0]["name"] == "catalog"
    assert upstreams[0]["path"] == "/api/catalog"

    await store.delete_upstream("upstream-1")
    assert await store.get_upstreams() == []


@pytest.mark.asyncio
async def test_remediation_approval_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "audit.db")
    await store.init_db()
    approval = RemediationApproval(
        approval_id="approval-1",
        action="drain_upstream",
        upstream_url="https://inventory.example.com",
        arguments={"severity": "high"},
        reason="Repeated failures",
        requested_at=datetime(2026, 1, 1, 10, 0, 0),
    )

    await store.save_approval(approval)
    approvals = await store.get_approvals()
    assert approvals[0]["status"] == "pending"
    assert approvals[0]["arguments"] == {"severity": "high"}

    await store.decide_approval("approval-1", "approved")
    await store.set_approval_status("approval-1", "executed")
    assert (await store.get_approval("approval-1"))["status"] == "executed"
