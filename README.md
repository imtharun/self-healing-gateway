# Self-Healing API Gateway

A FastAPI gateway and React operator console that route requests to registered
upstreams, contain failures with circuit breakers, use Gemini for incident
analysis, require human approval for high-impact remediation, and retain an
auditable incident history.

The public `/dashboard` is a safe, seeded portfolio walkthrough. Live status,
audit data, upstream configuration, and proxied requests are available only in
the authenticated `/operator` view.

## What it demonstrates

- Runtime upstream registration, editing, testing, draining removal, and
  PostgreSQL persistence.
- Continuous upstream health probes and per-upstream circuit breakers.
- Deterministic incident classification for first, flapping, and repeated
  failures.
- Gemini tool use constrained to registered upstreams and backed by an
  evaluation suite.
- Human approval before closing a circuit, draining an upstream, or creating an
  external incident ticket.
- A real outbound remediation integration through a configurable incident
  webhook.
- JSON application logs plus OpenTelemetry HTTP traces and gateway metrics.
- Protected operational APIs with signed, HTTP-only sessions and CSRF checks.
- GitHub Actions CI and Render deployment gated on successful checks.

## Architecture

```text
Public visitor -> React /dashboard -> seeded browser-only scenario

Operator -> React /operator -> signed session -> FastAPI gateway
                                               |-- managed route registry
                                               |-- health monitor
                                               |-- circuit breakers
                                               |-- incident policy + Gemini
                                               |-- approval queue
                                               |-- incident webhook
                                               `-- Neon PostgreSQL audit store

Authenticated client -> /api/* -> matching managed upstream
```

There are no built-in upstream services. Routes start empty and are added from
the operator dashboard, so unused local services and ports are not required.

## Local development

Generate local credentials using Python 3.12. Enter a password when prompted,
then copy the printed hash and generated session secret into `gateway/.env`:

```sh
cp gateway/.env.example gateway/.env
uv run --python 3.12 --with-requirements gateway/requirements.txt python -m gateway.auth
uv run --python 3.12 python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Start the backend and frontend:

```sh
docker compose -f gateway/docker-compose.yml up
```

Open:

- Public demo: `http://127.0.0.1:5173/dashboard`
- Operator login: `http://127.0.0.1:5173/operator/login`
- Backend health check: `http://127.0.0.1:8000/health`

The login password is the plain password entered when generating
`OPERATOR_PASSWORD_HASH`, not the hash or `OPERATOR_SESSION_SECRET`.

You can also run each service directly:

```sh
uv run --python 3.12 --with-requirements gateway/requirements.txt uvicorn gateway.app:app --reload --host 0.0.0.0 --port 8000
```

```sh
cd dashboard
npm install
cp .env.example .env
npm run dev
```

## Testing a live upstream

Sign in at `/operator`, choose **Add upstream**, and use the **PokéAPI test
preset**. Register it, then select **Test** on the new row. This creates:

- Gateway path: `/api/v2`
- Upstream URL: `https://pokeapi.co`
- Health path: `/api/v2/pokemon/pikachu`

The test sends an authenticated request through the gateway. Edit changes the
same persisted route without changing its identity. Remove immediately stops
new route matches, waits for in-flight requests to finish, and then deletes it.

Only add upstreams you own or are authorized to call. Public deployments reject
loopback, private, reserved, unresolved, and credential-bearing upstream URLs.

## Agent behavior and approvals

The deterministic policy classifies recent failures and passes its assessment
to Gemini. Gemini can inspect gateway state and recent events, open a circuit,
and produce an operator summary. These higher-impact tools create a pending
approval instead of executing immediately:

- `close_circuit`
- `drain_upstream`
- `create_incident_ticket`

An authenticated operator approves or rejects the request in `/operator`. The
ticket action posts a JSON payload to `INCIDENT_WEBHOOK_URL` only after approval.
Set `INCIDENT_WEBHOOK_TOKEN` when the receiver expects a bearer token.

The gateway does not currently restart containers or scale a platform service.
The webhook is the implemented real-world action and can target an incident
system or an automation service that performs an authorized follow-up.

## Evaluation suite

Run deterministic representative-incident evaluations:

```sh
uv run --python 3.12 --with-requirements gateway/requirements.txt python -m gateway.evals.run_evals
```

Compare live Gemini decisions against the same expected policy:

```sh
GEMINI_API_KEY=your-key uv run --python 3.12 --with-requirements gateway/requirements.txt python -m gateway.evals.run_evals --live
```

The deterministic suite runs in CI. The live comparison is deliberately manual
because it requires a secret, consumes model quota, and may expose model drift.

## Observability

Logs are emitted as JSON to standard output. FastAPI and outbound HTTPX calls
are instrumented with OpenTelemetry. Custom counters cover health checks,
proxied requests, and healing sessions.

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to send traces and metrics to an OTLP HTTP
collector. Without it, instrumentation remains active but no remote telemetry
is exported. `OTEL_SERVICE_NAME` and `LOG_LEVEL` control the service identity and
log threshold.

## Deployment

### Backend: Render + Neon

`render.yaml` defines a free Render web service built from
`gateway/Dockerfile`. It uses `/health` for health checks and
`autoDeployTrigger: checksPass`, so commits deploy only after GitHub checks pass.

Provide these Blueprint secrets:

- `DATABASE_URL`: a Neon pooled PostgreSQL URL with TLS enabled.
- `GEMINI_API_KEY`: Gemini API key for AI-assisted healing.
- `OPERATOR_PASSWORD_HASH`: generated by `python -m gateway.auth` under Python
  3.12.

Render generates `OPERATOR_SESSION_SECRET`. The Blueprint also keeps private
upstreams disabled and stores gateway tables in the `self_healing_gateway`
schema, allowing the app to share a Neon database without sharing tables.

Optional settings can be added to the Render service after Blueprint creation:

- `INCIDENT_WEBHOOK_URL`
- `INCIDENT_WEBHOOK_TOKEN`
- `OTEL_EXPORTER_OTLP_ENDPOINT`

### Frontend: Vercel

Use `dashboard` as the Vercel project root. `dashboard/vercel.json` serves the
client-side routes and rewrites `/backend/*` to the Render backend. This keeps
the operator cookie first-party at the browser. Git pushes build the frontend
through Vercel's Git integration; the same commits are validated by GitHub CI.

The frontend retries temporary network, 429, 502, 503, and 504 failures with
bounded backoff so a sleeping Render instance has time to wake up. It never
retries authentication failures.

## Environment variables

- `DATABASE_URL`: PostgreSQL persistence; SQLite is used locally when omitted.
- `GATEWAY_DB_SCHEMA`: PostgreSQL schema name.
- `GATEWAY_AUDIT_DB`: local SQLite path.
- `GATEWAY_CORS_ORIGINS`: comma-separated trusted frontend origins.
- `GEMINI_API_KEY`: enables Gemini incident analysis.
- `OPERATOR_PASSWORD_HASH`: PBKDF2 password hash for the operator account.
- `OPERATOR_SESSION_SECRET`: signs eight-hour operator sessions.
- `OPERATOR_COOKIE_SECURE`: disable only for local HTTP development.
- `GATEWAY_ALLOW_PRIVATE_UPSTREAMS`: allow private/local upstreams only in a
  trusted local environment.
- `INCIDENT_WEBHOOK_URL`: approved incident-ticket destination.
- `INCIDENT_WEBHOOK_TOKEN`: optional bearer token for the webhook.
- `LOG_LEVEL`: JSON log threshold.
- `OTEL_SERVICE_NAME`: OpenTelemetry resource name.
- `OTEL_EXPORTER_OTLP_ENDPOINT`: optional OTLP HTTP collector endpoint.

## Security and failure boundaries

- `/health` is public; gateway status, audit records, approvals, upstream
  management, and `/api/*` proxy routes require an operator session.
- State-changing requests require `X-Operator-CSRF: 1` in addition to the
  HTTP-only cookie.
- Upstream allow-listing and URL validation reduce SSRF risk, but this portfolio
  project is not a replacement for egress firewall rules or private network
  policy.
- Credentials are environment variables and must never be committed or exposed
  through `VITE_*` variables.
- The operator model is a single shared account; there is no RBAC, SSO, or
  per-user audit identity yet.
- Circuit state is in memory. Routes, approvals, events, and healing sessions
  persist, but circuit state resets when the service restarts.
- Approval execution is at-most-once at the application level. A failed webhook
  is marked failed and is not automatically retried.
- Multiple gateway replicas do not share circuit state or coordinate route
  draining. Run one instance until distributed state is implemented.
- When Gemini is unavailable, the request is recorded as skipped; proxy failure
  counting and health monitoring continue independently.

## Verification

```sh
uv run --isolated --python 3.12 --with-requirements gateway/requirements.txt python -m pytest gateway/tests -q
uv run --isolated --python 3.12 --with-requirements gateway/requirements.txt python -m gateway.evals.run_evals
npm --prefix dashboard run lint
npm --prefix dashboard run build
docker compose -f gateway/docker-compose.yml config --quiet
```
