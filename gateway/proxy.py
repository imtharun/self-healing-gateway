# third-party
import httpx

# fastapi
from fastapi import Response


async def forward_request(request, upstream_url):
    async with httpx.AsyncClient() as client:
        url = f"{upstream_url}{request.url.path}"
        res = await client.request(
            method=request.method,
            url=url,
        )

    return Response(
        status_code=res.status_code,
        content=res.content,
        headers=res.headers,
    )
