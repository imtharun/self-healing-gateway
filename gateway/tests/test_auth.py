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
