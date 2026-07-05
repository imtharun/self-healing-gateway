# Self-Healing Gateway

FastAPI gateway with upstream health checks, circuit breakers, AI-assisted remediation, audit logging, and a Vite React dashboard.

## Backend

```sh
cd gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn gateway.app:app --reload --host 0.0.0.0 --port 8000
```

Configuration lives in `gateway/config.yaml`.

Useful environment variables:

- `GEMINI_API_KEY`: enables AI-assisted healing sessions.
- `GATEWAY_AUDIT_DB`: overrides the SQLite audit DB path.
- `GATEWAY_CORS_ORIGINS`: comma-separated origins allowed to call the API.

## Dashboard

```sh
cd dashboard
npm install
cp .env.example .env
npm run dev
```

The dashboard reads `VITE_API_URL`, defaulting to `http://127.0.0.1:8000`.

## Tests

```sh
cd gateway
pytest
```

```sh
cd dashboard
npm run build
```
