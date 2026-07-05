# built-in
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

# fastapi
from fastapi import FastAPI, HTTPException, Request, status

from gateway.agent.gemini_agent import run_healing_session
from gateway.audit.models import HealingSession
from gateway.audit.store import init_db, save_session, get_sessions
from gateway.proxy import forward_request
from gateway.resilience.health_monitor import HealthMonitor
from gateway.resilience.registry import build_registry

# local
from gateway.router import get_upstream, load_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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


@app.api_route("/test/heal", methods=["GET"])
async def test_heal(request: Request):
    session_id = str(uuid.uuid4())
    triggered_at = datetime.now()

    result = await run_healing_session(
        upstream_url="http://localhost:9001",
        context="Sudden failure noticed in the upstream",
        cb_registry=app.state.cb_registry,
        health_monitor=app.state.health_monitor,
    )

    session: HealingSession = HealingSession(
        session_id=session_id,
        upstream_url=result["upstream_url"],
        triggered_at=triggered_at,
        resolved_at=datetime.now(),
        status=result["status"],
        reason=result.get("reason", ""),
        actions_taken=result.get("actions_taken", []),
    )

    await save_session(session=session)
    return result

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
