# built-in
import asyncio
import os
from contextlib import asynccontextmanager, suppress

# third-party
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

# local
from gateway.audit.store import get_sessions, init_db
from gateway.failure_detector import FailureDetector
from gateway.proxy import forward_request
from gateway.resilience.health_monitor import HealthMonitor
from gateway.resilience.registry import build_registry
from gateway.router import get_upstream, load_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("Startup Complete")

    config = load_config()
    app.state.cb_registry = build_registry(config)
    monitor = HealthMonitor(routes=config["routes"])
    monitor_task = asyncio.create_task(monitor.start())
    app.state.health_monitor = monitor
    detector = FailureDetector(
        health_monitor=monitor, cb_registry=app.state.cb_registry
    )
    detector_task = asyncio.create_task(detector.start())

    yield

    monitor_task.cancel()
    detector_task.cancel()
    with suppress(asyncio.CancelledError):
        await monitor_task
    with suppress(asyncio.CancelledError):
        await detector_task
    print("Shutdown Complete")


app = FastAPI(lifespan=lifespan)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "GATEWAY_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

# Add CORS for the React Dev Server.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/gateway/health-status")
async def health_status():
    health_data = app.state.health_monitor.health_status
    cb_registry = app.state.cb_registry

    status_report = {}
    for upstream_url, is_healthy in health_data.items():
        cb = cb_registry.get(upstream_url)
        status_report[upstream_url] = {
            "is_healthy": is_healthy,
            "circuit_state": cb.current_state.value if cb else "UNKNOWN",
            "failure_count": cb.failure_count if cb else 0,
        }
    return status_report


@app.get("/audit/sessions")
async def audit_sessions():
    return await get_sessions()


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request):
    path = request.url.path
    upstream_url = get_upstream(request_path=path)
    if upstream_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No upstream found for {path}",
        )
    res = await forward_request(
        request=request,
        upstream_url=upstream_url,
        cb_registry=app.state.cb_registry,
    )
    return res
