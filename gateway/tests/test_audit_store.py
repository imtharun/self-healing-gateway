# built-in
from datetime import datetime

# third-party
import pytest

# local
from gateway.audit.models import HealingSession
from gateway.audit import store


@pytest.mark.asyncio
async def test_save_and_get_sessions_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "audit.db")
    await store.init_db()

    session = HealingSession(
        session_id="session-1",
        upstream_url="http://localhost:9001",
        triggered_at=datetime(2026, 1, 1, 10, 0, 0),
        resolved_at=datetime(2026, 1, 1, 10, 0, 5),
        status="resolved",
        reason="Circuit opened",
        actions_taken=["get_upstream_state", "open_circuit"],
    )

    await store.save_session(session)
    sessions = await store.get_sessions()

    assert sessions[0]["session_id"] == "session-1"
    assert sessions[0]["actions_taken"] == [
        "get_upstream_state",
        "open_circuit",
    ]
