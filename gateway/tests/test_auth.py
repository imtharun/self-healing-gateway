import httpx
import pytest
from fastapi import HTTPException

from gateway.app import app
from gateway.auth import (
    SESSION_TTL_SECONDS,
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)
from gateway.resilience.circuit_breaker import CircuitStatus
from gateway.upstreams.models import ManagedUpstream
from gateway.upstreams.manager import UpstreamManager


def test_password_hash_verification():
    encoded_hash = hash_password("correct horse battery staple", salt=b"fixed-test-salt")

    assert verify_password("correct horse battery staple", encoded_hash)
    assert not verify_password("wrong password", encoded_hash)
    assert not verify_password("password", "invalid-hash")


def test_session_token_is_signed_and_expires(monkeypatch):
    monkeypatch.setenv("OPERATOR_SESSION_SECRET", "s" * 48)
    token = create_session_token(now=100)

    assert verify_session_token(token, now=101)["sub"] == "operator"

    with pytest.raises(HTTPException) as expired:
        verify_session_token(token, now=100 + SESSION_TTL_SECONDS)
    assert expired.value.status_code == 401

    with pytest.raises(HTTPException) as tampered:
        verify_session_token(f"{token}x", now=101)
    assert tampered.value.status_code == 401


@pytest.mark.asyncio
async def test_operator_login_session_and_logout(monkeypatch):
    monkeypatch.setenv("OPERATOR_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("OPERATOR_PASSWORD_HASH", hash_password("demo-password"))
    monkeypatch.setenv("OPERATOR_COOKIE_SECURE", "false")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/audit/sessions")
        assert unauthorized.status_code == 401

        invalid_login = await client.post(
            "/auth/login", json={"password": "wrong-password"}
        )
        assert invalid_login.status_code == 401

        login = await client.post(
            "/auth/login", json={"password": "demo-password"}
        )
        assert login.status_code == 200
        assert login.json() == {"authenticated": True, "role": "operator"}
        assert "HttpOnly" in login.headers["set-cookie"]

        session = await client.get("/auth/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True

        missing_csrf = await client.post("/auth/logout")
        assert missing_csrf.status_code == 403

        logout = await client.post(
            "/auth/logout", headers={"X-Operator-CSRF": "1"}
        )
        assert logout.status_code == 200

        expired_session = await client.get("/auth/session")
        assert expired_session.status_code == 401


@pytest.mark.asyncio
async def test_gateway_proxy_requires_operator_session(monkeypatch):
    monkeypatch.setenv("OPERATOR_SESSION_SECRET", "s" * 48)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/payments")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upstream_management_requires_session_and_csrf(monkeypatch):
    monkeypatch.setenv("OPERATOR_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("OPERATOR_PASSWORD_HASH", hash_password("demo-password"))
    monkeypatch.setenv("OPERATOR_COOKIE_SECURE", "false")

    async def no_op(*_args, **_kwargs):
        return None

    async def normalize_url(value):
        return value.rstrip("/")

    manager = UpstreamManager([], [])
    app.state.upstream_manager = manager
    app.state.cb_registry = manager.cb_registry
    app.state.health_monitor = type(
        "TestHealthMonitor", (), {"routes": [], "health_status": {}}
    )()
    manager.attach_monitor(app.state.health_monitor)
    monkeypatch.setattr("gateway.upstreams.manager.save_upstream", no_op)
    monkeypatch.setattr("gateway.upstreams.manager.update_upstream", no_op)
    monkeypatch.setattr("gateway.upstreams.manager.delete_upstream", no_op)
    monkeypatch.setattr("gateway.upstreams.manager.record_event", no_op)
    monkeypatch.setattr("gateway.app.validate_upstream_url", normalize_url)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/operator/upstreams")
        assert unauthorized.status_code == 401

        await client.post("/auth/login", json={"password": "demo-password"})
        payload = {
            "name": "inventory",
            "path": "/api/inventory",
            "upstream_url": "https://inventory.example.com",
            "health_check": "/health",
            "failure_threshold": 3,
            "recovery_timeout": 30,
        }
        missing_csrf = await client.post("/operator/upstreams", json=payload)
        assert missing_csrf.status_code == 403

        created = await client.post(
            "/operator/upstreams",
            json=payload,
            headers={"X-Operator-CSRF": "1"},
        )
        assert created.status_code == 201
        upstream_id = created.json()["upstream_id"]

        listed = await client.get("/operator/upstreams")
        assert listed.status_code == 200
        assert listed.json()[0]["path"] == "/api/inventory"

        updated_payload = {**payload, "name": "catalog", "path": "/api/catalog"}
        updated = await client.put(
            f"/operator/upstreams/{upstream_id}",
            json=updated_payload,
            headers={"X-Operator-CSRF": "1"},
        )
        assert updated.status_code == 200
        assert updated.json()["path"] == "/api/catalog"

        removed = await client.delete(
            f"/operator/upstreams/{upstream_id}",
            headers={"X-Operator-CSRF": "1"},
        )
        assert removed.status_code == 200
        assert removed.json()["removed"] is True


@pytest.mark.asyncio
async def test_operator_approval_executes_only_after_authenticated_decision(monkeypatch):
    monkeypatch.setenv("OPERATOR_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("OPERATOR_PASSWORD_HASH", hash_password("demo-password"))
    monkeypatch.setenv("OPERATOR_COOKIE_SECURE", "false")
    upstream = ManagedUpstream(
        upstream_id="inventory-1",
        name="inventory",
        path="/api/inventory",
        upstream_url="https://inventory.example.com",
        health_check="/health",
    )
    manager = UpstreamManager([], [upstream.as_route()])
    app.state.upstream_manager = manager
    app.state.cb_registry = manager.cb_registry
    manager.cb_registry[upstream.upstream_url].state = CircuitStatus.open
    decisions = []
    statuses = []

    async def fake_get_approval(_approval_id):
        return {
            "approval_id": "approval-1",
            "action": "close_circuit",
            "upstream_url": upstream.upstream_url,
            "arguments": {},
            "reason": "Health recovered",
            "status": "pending",
        }

    async def fake_decide(approval_id, decision):
        decisions.append((approval_id, decision))

    async def fake_set_status(approval_id, approval_status):
        statuses.append((approval_id, approval_status))

    async def no_op(**_kwargs):
        return None

    monkeypatch.setattr("gateway.app.get_approval", fake_get_approval)
    monkeypatch.setattr("gateway.app.decide_approval", fake_decide)
    monkeypatch.setattr("gateway.app.set_approval_status", fake_set_status)
    monkeypatch.setattr("gateway.app.record_event", no_op)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.post(
            "/operator/approvals/approval-1/decision",
            json={"decision": "approve"},
            headers={"X-Operator-CSRF": "1"},
        )
        assert unauthorized.status_code == 401

        await client.post("/auth/login", json={"password": "demo-password"})
        missing_csrf = await client.post(
            "/operator/approvals/approval-1/decision",
            json={"decision": "approve"},
        )
        assert missing_csrf.status_code == 403

        approved = await client.post(
            "/operator/approvals/approval-1/decision",
            json={"decision": "approve"},
            headers={"X-Operator-CSRF": "1"},
        )

    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    assert decisions == [("approval-1", "approved")]
    assert statuses == [("approval-1", "executed")]
    assert manager.cb_registry[upstream.upstream_url].current_state == CircuitStatus.closed
