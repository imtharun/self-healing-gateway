# Self-Healing API Gateway

A FastAPI-based API gateway that detects unhealthy upstream services, isolates failures with health-gated circuit breakers, runs Gemini-assisted remediation, records an audit/event trail, and exposes a real-time React operations dashboard.

## What It Demonstrates

- Health-gated circuit breaker recovery: unhealthy upstreams stay blocked until health checks recover.
- AI-assisted remediation with Gemini tool calls.
- Agentic incident memory: Gemini inspects recent gateway events before choosing a remediation action.
- Repeated-failure escalation policy that classifies first failures, flapping services, and repeated failures.
- Persistent healing-session audit logs.
- Gateway event timeline for health failures, circuit transitions, trial traffic, and healing completion.
- Real-time React dashboard for upstream state, events, and operator summaries.

## Architecture

```text
Client
  |
  v
FastAPI Gateway :8000
  |-- /api/payments -> payments mock upstream :9001
  |-- /api/orders   -> orders mock upstream :9002
  |
  |-- HealthMonitor checks /health
  |-- CircuitBreaker blocks or allows traffic
  |-- FailureDetector classifies incidents and starts Gemini healing sessions
  |-- SQLite audit/event store
  v
React Dashboard :5173
```

## Quick Demo

Start the gateway, dashboard, and two mock upstream services:

```sh
docker compose -f gateway/docker-compose.yml up
```

Open the dashboard:

```text
http://127.0.0.1:5173
```

## Screenshots

Dashboard screenshots can be stored in `docs/screenshots/` after running the demo stack. Capture the dashboard with the summary cards, upstream list, recent timeline, and audit log visible.

Send traffic through the gateway:

```sh
curl -i http://127.0.0.1:8000/api/payments
curl -i http://127.0.0.1:8000/api/orders
```

Mark the payments upstream unhealthy:

```sh
curl -X POST http://127.0.0.1:9001/admin/unhealthy
```

Watch the dashboard show the health failure, circuit state, timeline event, and healing audit entry.

Recover the payments upstream:

```sh
curl -X POST http://127.0.0.1:9001/admin/healthy
```

After the circuit recovery timeout, send a trial request through the gateway:

```sh
curl -i http://127.0.0.1:8000/api/payments
```

The successful request closes the half-open circuit.

## Local Development

Backend:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r gateway/requirements.txt
cp gateway/.env.example gateway/.env
uvicorn gateway.app:app --reload --host 0.0.0.0 --port 8000
```

Mock upstreams:

```sh
MOCK_SERVICE_NAME=payments uvicorn gateway.mock_upstream:app --reload --port 9001
MOCK_SERVICE_NAME=orders uvicorn gateway.mock_upstream:app --reload --port 9002
```

Dashboard:

```sh
cd dashboard
npm install
cp .env.example .env
npm run dev
```

## Configuration

Gateway routes live in `gateway/config.yaml`.

Useful environment variables:

- `GEMINI_API_KEY`: enables Gemini-assisted healing summaries and tool decisions.
- `GATEWAY_AUDIT_DB`: SQLite path for audit/event storage.
- `GATEWAY_CORS_ORIGINS`: comma-separated dashboard origins.
- `PAYMENTS_UPSTREAM_URL`: override `/api/payments` upstream.
- `ORDERS_UPSTREAM_URL`: override `/api/orders` upstream.

## API Examples

Gateway status:

```sh
curl http://127.0.0.1:8000/gateway/health-status
curl http://127.0.0.1:8000/gateway/summary
```

Audit and event trail:

```sh
curl http://127.0.0.1:8000/audit/sessions
curl http://127.0.0.1:8000/audit/events
```

Mock upstream controls:

```sh
curl -X POST http://127.0.0.1:9001/admin/unhealthy
curl -X POST http://127.0.0.1:9001/admin/healthy
curl -X POST http://127.0.0.1:9001/admin/fail-requests
curl -X POST http://127.0.0.1:9001/admin/recover-requests
```

The mock `/admin/*` endpoints are demo-only controls. They are enabled in Docker Compose with `ENABLE_MOCK_ADMIN=true` and should not be exposed in production.

## Tests

Backend:

```sh
python3 -m pytest gateway/tests
```

Frontend:

```sh
cd dashboard
npm run build
npm run lint
```

Compose syntax:

```sh
docker compose -f gateway/docker-compose.yml config --quiet
```
