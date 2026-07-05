# third-party
import httpx
import pytest
from starlette.datastructures import Headers

# local
from gateway.proxy import _forward_headers, forward_request
from gateway.resilience.circuit_breaker import CircuitBreaker


class FakeRequest:
    method = "POST"
    url = httpx.URL("http://gateway.local/api/payments/charge?trace=1")
    headers = Headers(
        {
            "host": "gateway.local",
            "content-type": "application/json",
            "x-request-id": "req-1",
        }
    )

    async def body(self):
        return b'{"amount":10}'


class FakeClient:
    captured = None

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def request(self, **kwargs):
        FakeClient.captured = kwargs
        return httpx.Response(
            200,
            content=b'{"ok":true}',
            headers={"content-type": "application/json"},
        )


def test_forward_headers_strips_hop_by_hop_headers():
    headers = _forward_headers(
        Headers(
            {
                "host": "gateway.local",
                "connection": "keep-alive",
                "content-length": "10",
                "x-request-id": "req-1",
            }
        )
    )

    assert headers == {"x-request-id": "req-1"}


@pytest.mark.asyncio
async def test_forward_request_preserves_body_query_and_headers(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    cb = CircuitBreaker(name="payments")

    response = await forward_request(
        FakeRequest(),
        "http://upstream.local",
        {"http://upstream.local": cb},
    )

    assert response.status_code == 200
    assert FakeClient.captured["method"] == "POST"
    assert str(FakeClient.captured["url"]) == (
        "http://upstream.local/api/payments/charge?trace=1"
    )
    assert FakeClient.captured["content"] == b'{"amount":10}'
    assert FakeClient.captured["headers"]["x-request-id"] == "req-1"
