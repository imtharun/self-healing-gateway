# built-in
from typing import Dict

# third-party
import httpx
from fastapi import HTTPException
from fastapi import Response
from fastapi import status

# local
from gateway.audit.store import record_event
from gateway.resilience.circuit_breaker import CircuitBreaker
from gateway.resilience.circuit_breaker import CircuitStatus

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
    cb = cb_registry[upstream_url]

    if cb.is_open():
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
        previous_state = cb.current_state
        cb.record_failure()
        await record_event(
            event_type="upstream_request_failed",
            upstream_url=upstream_url,
            message=f"Request to {upstream_url} failed with {exc.__class__.__name__}.",
            metadata={
                "path": request.url.path,
                "previous_state": previous_state.value,
                "current_state": cb.current_state.value,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream request failed: {exc.__class__.__name__}",
        ) from exc

    previous_state = cb.current_state
    if res.status_code >= 500:
        cb.record_failure()
        await record_event(
            event_type="upstream_request_failed",
            upstream_url=upstream_url,
            message=f"{upstream_url} returned HTTP {res.status_code}.",
            metadata={
                "path": request.url.path,
                "status_code": res.status_code,
                "previous_state": previous_state.value,
                "current_state": cb.current_state.value,
            },
        )
    else:
        cb.record_success()
        if previous_state == CircuitStatus.half_open:
            await record_event(
                event_type="circuit_closed",
                upstream_url=upstream_url,
                message=(
                    f"Trial request to {upstream_url} succeeded; "
                    "circuit is closed."
                ),
                metadata={"path": request.url.path, "status_code": res.status_code},
            )

    return Response(
        status_code=res.status_code,
        content=res.content,
        headers=_forward_headers(res.headers),
    )
