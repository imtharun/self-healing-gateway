# Self-Healing API Gateway

A FastAPI-based API gateway that detects unhealthy upstream services, isolates failures with health-gated circuit breakers, runs Gemini-assisted remediation, records an audit/event trail, and exposes public demo and authenticated operator views.

## What It Demonstrates

- Health-gated circuit breaker recovery: unhealthy upstreams stay blocked until health checks recover.
- AI-assisted remediation with Gemini tool calls.
- Agentic incident memory: Gemini inspects recent gateway events before choosing a remediation action.
- Repeated-failure escalation policy that classifies first failures, flapping services, and repeated failures.
- Persistent healing-session audit logs.
- Gateway event timeline for health failures, circuit transitions, trial traffic, and healing completion.
- Safe public incident simulation for portfolio visitors.
- Authenticated operator dashboard for live upstream state, events, and audit records.

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

Open the public demo:

```text
http://127.0.0.1:5173/dashboard
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

Create local operator credentials. Keep these values out of Git:

```sh
python3 -m gateway.auth
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Copy the generated password hash and session secret into `gateway/.env` as
`OPERATOR_PASSWORD_HASH` and `OPERATOR_SESSION_SECRET`.

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

## Production Deployment

### Backend on Render

The repository includes a production Docker image and a Render Blueprint. In
Render, create a new Blueprint from this repository. Render reads
`render.yaml`, creates the `self-healing-gateway-api` web service, and verifies
deployments through `/health`.

During Blueprint creation, provide these environment variables when prompted:

- `DATABASE_URL`: Neon pooled PostgreSQL connection string. In Neon, choose
  the pooled connection string and keep `sslmode=require` enabled.
- `PAYMENTS_UPSTREAM_URL`: public or private URL for the payments service.
- `ORDERS_UPSTREAM_URL`: public or private URL for the orders service.
- `GEMINI_API_KEY`: Gemini API key used by healing sessions.
- `OPERATOR_PASSWORD_HASH`: generated with `python3 -m gateway.auth`.

The mock upstreams are local development services and are intentionally not published
by the Render Blueprint. Point the two upstream variables at real deployed
services. The Blueprint uses Render's free web service and stores audit data in
Neon PostgreSQL under the isolated `self_healing_gateway` schema. Neon can
scale an inactive database to zero and automatically wake it on the next
connection. SQLite remains the local-development fallback when `DATABASE_URL`
is not set.

### Dashboard on Vercel

Keep `dashboard` as the Vercel project root. The public site opens on the
product overview at `/`, provides a safe seeded scenario at `/dashboard`, and
sends authenticated operators through `/operator/login` to `/operator`.
`dashboard/vercel.json` proxies `/backend/*` to Render so the secure operator
cookie remains first-party and keeps direct visits to all frontend routes
working.

Set `OPERATOR_PASSWORD_HASH` in Render using the generated value. Render
generates `OPERATOR_SESSION_SECRET` from the Blueprint. Do not expose either
value through Vercel or a `VITE_*` variable.

If the frontend domain changes, update `GATEWAY_CORS_ORIGINS` in `render.yaml`
or in the Render service settings before deploying.

## Configuration

Gateway routes live in `gateway/config.yaml`.

Useful environment variables:

- `GEMINI_API_KEY`: enables Gemini-assisted healing summaries and tool decisions.
- `DATABASE_URL`: enables PostgreSQL audit storage when set.
- `GATEWAY_DB_SCHEMA`: isolates gateway tables within a shared PostgreSQL database.
- `GATEWAY_AUDIT_DB`: SQLite path for audit/event storage.
- `GATEWAY_CORS_ORIGINS`: comma-separated dashboard origins.
- `PAYMENTS_UPSTREAM_URL`: override `/api/payments` upstream.
- `ORDERS_UPSTREAM_URL`: override `/api/orders` upstream.
- `OPERATOR_PASSWORD_HASH`: PBKDF2 hash used for the single operator login.
- `OPERATOR_SESSION_SECRET`: random secret used to sign eight-hour sessions.
- `OPERATOR_COOKIE_SECURE`: set to `false` only for local HTTP development.

## Access Control

`/health` remains public for Render health checks. Gateway status, audit data,
and proxied upstream routes require a signed operator session. Non-GET proxy
requests and logout also require the `X-Operator-CSRF: 1` header. The public
dashboard uses only seeded browser data and never reads operational records.

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
