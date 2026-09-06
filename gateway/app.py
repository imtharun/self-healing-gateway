# built-in
import asyncio
import os
from contextlib import asynccontextmanager, suppress

# third-party
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# local
from gateway.auth import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    auth_is_configured,
    clear_failed_logins,
    cookie_is_secure,
    create_session_token,
    login_allowed,
    record_failed_login,
    require_csrf_header,
    require_operator,
    verify_password,
)
from gateway.audit.store import (
    close_db,
    get_events,
    get_sessions,
    get_upstreams,
    init_db,
)
from gateway.failure_detector import FailureDetector
from gateway.proxy import forward_request
from gateway.resilience.health_monitor import HealthMonitor
from gateway.router import load_config
from gateway.upstreams.manager import (
    UpstreamConflictError,
    UpstreamManager,
    UpstreamNotFoundError,
)
from gateway.upstreams.models import ManagedUpstream, UpstreamCreate
from gateway.upstreams.validation import validate_upstream_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("Startup Complete")

    config = load_config()
    manager = UpstreamManager(
        static_routes=config["routes"], managed_routes=await get_upstreams()
    )
    app.state.upstream_manager = manager
    app.state.cb_registry = manager.cb_registry
    monitor = HealthMonitor(routes=manager.routes)
    manager.attach_monitor(monitor)
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
    await close_db()
    print("Shutdown Complete")


app = FastAPI(lifespan=lifespan)


class OperatorLogin(BaseModel):
    password: str = Field(min_length=1, max_length=256)

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


@app.post("/auth/login")
async def operator_login(payload: OperatorLogin, request: Request, response: Response):
    if not auth_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator authentication is not configured",
        )

    client_key = request.client.host if request.client else "unknown"
    if not login_allowed(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )

    password_hash = os.environ["OPERATOR_PASSWORD_HASH"]
    if not verify_password(payload.password, password_hash):
        record_failed_login(client_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operator credentials",
        )

    clear_failed_logins(client_key)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=cookie_is_secure(request),
        samesite="lax",
        path="/",
    )
    return {"authenticated": True, "role": "operator"}


@app.get("/auth/session")
async def operator_session(operator: dict = Depends(require_operator)):
    return {"authenticated": True, "role": operator["sub"]}


@app.post("/auth/logout")
async def operator_logout(
    request: Request,
    response: Response,
    _operator: dict = Depends(require_operator),
):
    require_csrf_header(request)
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=cookie_is_secure(request),
        samesite="lax",
    )
    return {"authenticated": False}


@app.get("/gateway/health-status")
async def health_status(_operator: dict = Depends(require_operator)):
    health_data = app.state.health_monitor.health_status
    cb_registry = app.state.cb_registry

    status_report = {}
    for route in app.state.upstream_manager.list_upstreams():
        upstream_url = route["upstream_url"]
        is_healthy = health_data.get(upstream_url, False)
        cb = cb_registry.get(upstream_url)
        status_report[upstream_url] = {
            "is_healthy": is_healthy,
            "circuit_state": cb.current_state.value if cb else "UNKNOWN",
            "failure_count": cb.failure_count if cb else 0,
        }
    return status_report


@app.get("/gateway/summary")
async def gateway_summary(_operator: dict = Depends(require_operator)):
    status_report = await health_status(_operator)
    upstreams = list(status_report.values())
    return {
        "total_upstreams": len(upstreams),
        "healthy_upstreams": sum(1 for item in upstreams if item["is_healthy"]),
        "unhealthy_upstreams": sum(1 for item in upstreams if not item["is_healthy"]),
        "open_circuits": sum(
            1 for item in upstreams if item["circuit_state"] == "OPEN"
        ),
        "half_open_circuits": sum(
            1 for item in upstreams if item["circuit_state"] == "HALF_OPEN"
        ),
    }


@app.get("/operator/upstreams")
async def operator_upstreams(_operator: dict = Depends(require_operator)):
    manager = app.state.upstream_manager
    health_data = app.state.health_monitor.health_status
    return [
        {
            **route,
            "is_healthy": health_data.get(route["upstream_url"], False),
            "active_requests": manager.active_request_count(route["upstream_id"]),
        }
        for route in manager.list_upstreams()
    ]


@app.post(
    "/operator/upstreams",
    status_code=status.HTTP_201_CREATED,
)
async def add_operator_upstream(
    payload: UpstreamCreate,
    request: Request,
    _operator: dict = Depends(require_operator),
):
    require_csrf_header(request)
    try:
        upstream_url = await validate_upstream_url(payload.upstream_url)
        upstream = ManagedUpstream(
            **{**payload.model_dump(), "upstream_url": upstream_url}
        )
        return await app.state.upstream_manager.add(upstream)
    except UpstreamConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@app.delete("/operator/upstreams/{upstream_id}")
async def remove_operator_upstream(
    upstream_id: str,
    request: Request,
    _operator: dict = Depends(require_operator),
):
    require_csrf_header(request)
    try:
        removed = await app.state.upstream_manager.remove(upstream_id)
    except UpstreamNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return {"removed": True, "upstream": removed}


@app.get("/audit/sessions")
async def audit_sessions(_operator: dict = Depends(require_operator)):
    return await get_sessions()


@app.get("/audit/events")
async def audit_events(_operator: dict = Depends(require_operator)):
    return await get_events()


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request):
    await require_operator(request)
    if request.method != "GET":
        require_csrf_header(request)
    path = request.url.path
    async with app.state.upstream_manager.resolve(path) as route:
        if route is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No upstream found for {path}",
            )
        return await forward_request(
            request=request,
            upstream_url=route["upstream_url"],
            cb_registry=app.state.cb_registry,
        )
