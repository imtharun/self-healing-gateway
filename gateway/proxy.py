# built-in
from typing import Dict

# third-party
import httpx
from fastapi import HTTPException
from fastapi import Response
from fastapi import status

# local
from gateway.resilience.circuit_breaker import CircuitBreaker

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _forward_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS | {"host", "content-length"}
    }


def _query_bytes(query) -> bytes:
    if isinstance(query, bytes):
        return query
    return str(query).encode()


async def forward_request(
    request, upstream_url, cb_registry: Dict[str, CircuitBreaker]
):

    if cb_registry[upstream_url].is_open():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service currently unavailable. Please try again later.",
        )

    body = await request.body()
    url = httpx.URL(upstream_url).join(request.url.path).copy_with(
        query=_query_bytes(request.url.query)
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.request(
                method=request.method,
                url=url,
                content=body,
                headers=_forward_headers(request.headers),
            )
    except httpx.HTTPError as exc:
        cb_registry[upstream_url].record_failure()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream request failed: {exc.__class__.__name__}",
        ) from exc

    if res.status_code >= 500:
        cb_registry[upstream_url].record_failure()
    else:
        cb_registry[upstream_url].record_success()

    return Response(
        status_code=res.status_code,
        content=res.content,
        headers=_forward_headers(res.headers),
    )
