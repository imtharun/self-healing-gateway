# built-in
import asyncio
import socket

# third-party
import pytest

# local
from gateway.upstreams.manager import UpstreamConflictError, UpstreamManager
from gateway.upstreams.models import ManagedUpstream
from gateway.upstreams.validation import validate_upstream_url


class FakeHealthMonitor:
    def __init__(self):
        self.routes = []
        self.health_status = {}


def build_upstream(**overrides):
    values = {
        "upstream_id": "inventory-1",
        "name": "inventory",
        "path": "/api/inventory",
        "upstream_url": "https://inventory.example.com",
        "health_check": "/health",
        "failure_threshold": 3,
        "recovery_timeout": 45,
    }
    return ManagedUpstream(**{**values, **overrides})


@pytest.mark.asyncio
async def test_manager_adds_persists_and_routes_upstream(monkeypatch):
    saved = []
    events = []

    async def fake_save(upstream):
        saved.append(upstream)

    async def fake_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr("gateway.upstreams.manager.save_upstream", fake_save)
    monkeypatch.setattr("gateway.upstreams.manager.record_event", fake_event)
    manager = UpstreamManager([], [])
    monitor = FakeHealthMonitor()
    manager.attach_monitor(monitor)

    route = await manager.add(build_upstream())

    assert saved[0].upstream_id == "inventory-1"
    assert monitor.routes[0]["path"] == "/api/inventory"
    assert manager.cb_registry[route["upstream_url"]].failure_threshold == 3
    assert events[0]["event_type"] == "upstream_added"
    async with manager.resolve("/api/inventory/items") as resolved:
        assert resolved["upstream_id"] == "inventory-1"


@pytest.mark.asyncio
async def test_manager_rejects_duplicate_route(monkeypatch):
    async def fake_save(_upstream):
        return None

    async def fake_event(**_kwargs):
        return None

    monkeypatch.setattr("gateway.upstreams.manager.save_upstream", fake_save)
    monkeypatch.setattr("gateway.upstreams.manager.record_event", fake_event)
    manager = UpstreamManager([], [])
    await manager.add(build_upstream())

    with pytest.raises(UpstreamConflictError, match="route path"):
        await manager.add(
            build_upstream(
                upstream_id="inventory-2",
                name="inventory-copy",
                upstream_url="https://inventory-copy.example.com",
            )
        )


@pytest.mark.asyncio
async def test_manager_updates_managed_upstream(monkeypatch):
    updated = []
    events = []

    async def fake_update(upstream):
        updated.append(upstream)

    async def fake_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr("gateway.upstreams.manager.update_upstream", fake_update)
    monkeypatch.setattr("gateway.upstreams.manager.record_event", fake_event)
    manager = UpstreamManager([], [build_upstream().as_route()])
    monitor = FakeHealthMonitor()
    monitor.health_status["https://inventory.example.com"] = True
    manager.attach_monitor(monitor)

    replacement = build_upstream(
        name="catalog",
        path="/api/catalog",
        upstream_url="https://catalog.example.com",
    )
    route = await manager.update(replacement)

    assert updated[0].name == "catalog"
    assert route["path"] == "/api/catalog"
    assert "https://inventory.example.com" not in manager.cb_registry
    assert "https://catalog.example.com" in manager.cb_registry
    assert events[0]["event_type"] == "upstream_updated"


@pytest.mark.asyncio
async def test_missing_route_does_not_suppress_caller_exception():
    manager = UpstreamManager([], [])

    with pytest.raises(RuntimeError, match="not found"):
        async with manager.resolve("/api/missing") as route:
            assert route is None
            raise RuntimeError("not found")


@pytest.mark.asyncio
async def test_remove_drains_in_flight_request_before_cleanup(monkeypatch):
    deleted = []

    async def fake_delete(upstream_id):
        deleted.append(upstream_id)

    async def fake_event(**_kwargs):
        return None

    monkeypatch.setattr("gateway.upstreams.manager.delete_upstream", fake_delete)
    monkeypatch.setattr("gateway.upstreams.manager.record_event", fake_event)
    manager = UpstreamManager([], [build_upstream().as_route()])
    monitor = FakeHealthMonitor()
    manager.attach_monitor(monitor)

    async with manager.resolve("/api/inventory/items") as route:
        removal = asyncio.create_task(manager.remove(route["upstream_id"]))
        await asyncio.sleep(0)
        assert removal.done() is False
        assert manager.list_upstreams() == []
        assert route["upstream_url"] in manager.cb_registry

    removed = await removal
    assert removed["upstream_id"] == "inventory-1"
    assert deleted == ["inventory-1"]
    assert manager.cb_registry == {}
    assert monitor.routes == []


@pytest.mark.asyncio
async def test_url_validation_blocks_private_addresses(monkeypatch):
    monkeypatch.delenv("GATEWAY_ALLOW_PRIVATE_UPSTREAMS", raising=False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )

    with pytest.raises(ValueError, match="Private, local"):
        await validate_upstream_url("http://internal.example.com")


@pytest.mark.asyncio
async def test_url_validation_normalizes_public_url(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    result = await validate_upstream_url("https://EXAMPLE.com/")

    assert result == "https://example.com"
