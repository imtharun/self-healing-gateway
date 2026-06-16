# third-party
import httpx
from typing import Dict

# fastapi
from fastapi import status
from fastapi import Response
from fastapi import HTTPException

# local
from gateway.resilience.circuit_breaker import CircuitBreaker


async def forward_request(
    request, upstream_url, cb_registry: Dict[str, CircuitBreaker]
):

    if cb_registry[upstream_url].is_open():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service currently unavailable. Please try again later.",
        )

    async with httpx.AsyncClient() as client:
        url = f"{upstream_url}{request.url.path}"
        res = await client.request(
            method=request.method,
            url=url,
        )

        if res.status_code >= 500:
            
            cb_registry[upstream_url].record_failure()
        else:
            cb_registry[upstream_url].record_success()

    return Response(
        status_code=res.status_code,
        content=res.content,
        headers=res.headers,
    )
