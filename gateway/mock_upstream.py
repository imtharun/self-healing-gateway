# built-in
import os

# third-party
from fastapi import FastAPI, HTTPException, Request, Response, status

SERVICE_NAME = os.getenv("MOCK_SERVICE_NAME", "mock-upstream")

app = FastAPI(title=f"{SERVICE_NAME} Mock Upstream")
state = {
    "healthy": os.getenv("MOCK_HEALTHY", "true").lower() == "true",
    "fail_requests": os.getenv("MOCK_FAIL_REQUESTS", "false").lower() == "true",
}


def _require_dev_admin_enabled() -> None:
    if os.getenv("ENABLE_MOCK_ADMIN", "true").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mock admin controls are disabled.",
        )


@app.get("/health")
async def health():
    if not state["healthy"]:
        return Response(
            content='{"status":"unhealthy"}',
            media_type="application/json",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/admin/healthy")
async def mark_healthy():
    _require_dev_admin_enabled()
    state["healthy"] = True
    return {"service": SERVICE_NAME, "healthy": True}


@app.post("/admin/unhealthy")
async def mark_unhealthy():
    _require_dev_admin_enabled()
    state["healthy"] = False
    return {"service": SERVICE_NAME, "healthy": False}


@app.post("/admin/fail-requests")
async def fail_requests():
    _require_dev_admin_enabled()
    state["fail_requests"] = True
    return {"service": SERVICE_NAME, "fail_requests": True}


@app.post("/admin/recover-requests")
async def recover_requests():
    _require_dev_admin_enabled()
    state["fail_requests"] = False
    return {"service": SERVICE_NAME, "fail_requests": False}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def handle_request(path: str, request: Request):
    if state["fail_requests"]:
        return Response(
            content='{"error":"mock upstream request failure"}',
            media_type="application/json",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return {
        "service": SERVICE_NAME,
        "method": request.method,
        "path": f"/{path}",
        "status": "ok",
    }
