# built-in
import asyncio
from contextlib import asynccontextmanager

# fastapi
from fastapi import status
from fastapi import Request
from fastapi import FastAPI
from fastapi import HTTPException

# local
from gateway.router import load_config
from gateway.router import get_upstream
from gateway.proxy import forward_request
from gateway.resilience.registry import build_registry
from gateway.resilience.health_monitor import HealthMonitor


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Startup Complete")

    app.state.cb_registry = build_registry(load_config())
    monitor = HealthMonitor(routes=load_config()["routes"])
    task = asyncio.create_task(monitor.start())
    app.state.health_monitor = monitor

    yield

    task.cancel()
    print("Shutdown Complete")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/gateway/health-status")
async def health_status():
    health_data = app.state.health_monitor.health_status
    return health_data


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
