# third-party
import httpx
import pytest

# local
from gateway.agent.tools import create_incident_ticket


class FakeResponse:
    status_code = 202

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    request = None

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, **kwargs):
        FakeAsyncClient.request = {"url": url, **kwargs}
        return FakeResponse()


@pytest.mark.asyncio
async def test_incident_ticket_posts_only_to_configured_webhook(monkeypatch):
    monkeypatch.setenv("INCIDENT_WEBHOOK_URL", "https://incidents.example.com/hooks/gateway")
    monkeypatch.setenv("INCIDENT_WEBHOOK_TOKEN", "secret-token")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await create_incident_ticket(
        upstream_url="https://inventory.example.com",
        reason="Repeated gateway failures",
        severity="critical",
    )

    assert result["response_status"] == 202
    assert FakeAsyncClient.request["url"] == "https://incidents.example.com/hooks/gateway"
    assert FakeAsyncClient.request["headers"]["Authorization"] == "Bearer secret-token"
    assert FakeAsyncClient.request["json"]["severity"] == "critical"


@pytest.mark.asyncio
async def test_incident_ticket_requires_webhook_configuration(monkeypatch):
    monkeypatch.delenv("INCIDENT_WEBHOOK_URL", raising=False)

    with pytest.raises(RuntimeError, match="not configured"):
        await create_incident_ticket(
            upstream_url="https://inventory.example.com",
            reason="Repeated gateway failures",
        )
