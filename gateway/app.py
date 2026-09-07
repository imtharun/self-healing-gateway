# built-in
import asyncio
import logging
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
    decide_approval,
    get_approval,
    get_approvals,
    get_events,
    get_sessions,
    get_upstreams,
    init_db,
    record_event,
    set_approval_status,
)
from gateway.agent.tools import close_circuit, create_incident_ticket, drain_upstream
from gateway.failure_detector import FailureDetector
from gateway.observability import configure_observability
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
    logger.info("Gateway startup complete")

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
    logger.info("Gateway shutdown complete")


app = FastAPI(lifespan=lifespan)
configure_observability(app)
logger = logging.getLogger("gateway.api")


class OperatorLogin(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")

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


@app.put("/operator/upstreams/{upstream_id}")
async def update_operator_upstream(
    upstream_id: str,
    payload: UpstreamCreate,
    request: Request,
    _operator: dict = Depends(require_operator),
):
    require_csrf_header(request)
    try:
        upstream_url = await validate_upstream_url(payload.upstream_url)
        existing = next(
            (
                item
                for item in app.state.upstream_manager.list_upstreams()
                if item["upstream_id"] == upstream_id and item["managed"]
            ),
            None,
        )
        if existing is None:
            raise UpstreamNotFoundError("Managed upstream was not found")
        upstream = ManagedUpstream(
            **{
                **payload.model_dump(),
                "upstream_url": upstream_url,
                "upstream_id": upstream_id,
                "created_at": existing["created_at"],
            }
        )
        return await app.state.upstream_manager.update(upstream)
    except UpstreamConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except UpstreamNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@app.get("/audit/sessions")
async def audit_sessions(_operator: dict = Depends(require_operator)):
    return await get_sessions()


@app.get("/audit/events")
async def audit_events(_operator: dict = Depends(require_operator)):
    return await get_events()


@app.get("/operator/approvals")
async def operator_approvals(_operator: dict = Depends(require_operator)):
    return await get_approvals()


@app.post("/operator/approvals/{approval_id}/decision")
async def decide_operator_approval(
    approval_id: str,
    payload: ApprovalDecision,
    request: Request,
    _operator: dict = Depends(require_operator),
):
    require_csrf_header(request)
    approval = await get_approval(approval_id)
    if approval is None or approval["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending approval was not found",
        )

    if payload.decision == "reject":
        try:
            await decide_approval(approval_id, "rejected")
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This approval has already been decided",
            ) from exc
        await record_event(
            event_type="approval_rejected",
            upstream_url=approval["upstream_url"],
            message=f"Operator rejected {approval['action'].replace('_', ' ')}.",
            metadata={"approval_id": approval_id},
        )
        return {"approval_id": approval_id, "status": "rejected"}

    try:
        await decide_approval(approval_id, "approved")
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This approval has already been decided",
        ) from exc

    action = approval["action"]
    upstream_url = approval["upstream_url"]
    try:
        if upstream_url not in app.state.cb_registry:
            raise ValueError("The upstream is no longer registered")
        if action == "close_circuit":
            result = close_circuit(upstream_url, app.state.cb_registry)
        elif action == "drain_upstream":
            result = drain_upstream(upstream_url, app.state.cb_registry)
        elif action == "create_incident_ticket":
            result = await create_incident_ticket(
                upstream_url=upstream_url,
                reason=approval["arguments"].get("reason", approval["reason"]),
                severity=approval["arguments"].get("severity", "high"),
            )
        else:
            raise ValueError("Unsupported approval action")
    except Exception as exc:
        logger.exception(
            "Approved remediation failed",
            extra={"approval_id": approval_id, "action": approval["action"]},
        )
        await set_approval_status(approval_id, "failed")
        await record_event(
            event_type="approval_failed",
            upstream_url=approval["upstream_url"],
            message="An approved action failed during execution.",
            metadata={"approval_id": approval_id, "action": approval["action"]},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The approved action failed. Review backend logs for details.",
        ) from exc

    await set_approval_status(approval_id, "executed")
    await record_event(
        event_type="approval_executed",
        upstream_url=approval["upstream_url"],
        message=f"Operator approved and executed {approval['action'].replace('_', ' ')}.",
        metadata={"approval_id": approval_id, "result": result},
    )
    return {"approval_id": approval_id, "status": "executed", "result": result}


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
