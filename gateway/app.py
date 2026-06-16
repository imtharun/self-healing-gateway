# built-in
from fastapi import status
from fastapi import HTTPException
from contextlib import asynccontextmanager

# fastapi
from fastapi import FastAPI
from fastapi import Request

# local
from gateway.router import load_config
from gateway.router import get_upstream
from gateway.proxy import forward_request
from gateway.resilience.registry import build_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Startup Complete")
    app.state.cb_registry = build_registry(load_config())
    yield
    print("Shutdown Complete")


app = FastAPI(lifespan=lifespan)


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request):

    path = request.url.path
    upstream = get_upstream(request_path=path)
    if upstream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No upstream found for {path}",
        )
    res = await forward_request(
        request=request,
        upstream_url=upstream,
        cb_registry=app.state.cb_registry,
    )
    return res


@app.get("/health")
async def health():
    return {"status": "ok"}
