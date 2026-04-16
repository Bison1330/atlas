# atlas-api

FastAPI gateway for Atlas.

In Milestone 0 this service exposes only observability endpoints:

- `GET /health` — liveness. Returns `{"status": "ok"}` without touching dependencies.
- `GET /health/ready` — readiness. Pings Postgres and Redis; returns 200 only if both respond, 503 otherwise with per-dependency detail.

Configuration is loaded from environment variables (see `app/core/config.py`) and validated with Pydantic Settings.

## Layout

```
app/
├── main.py              App factory, middleware wiring, Sentry init
├── core/
│   ├── config.py        Settings (env vars)
│   ├── logging.py       structlog setup
│   ├── db.py            SQLAlchemy engine + session
│   └── redis.py         Redis client
├── middleware/
│   └── request_id.py    Request-ID propagation + logging binding
├── routes/
│   └── health.py        /health, /health/ready
└── migrations/          Alembic
```

## Run locally (without Docker)

```bash
uv sync
uv run uvicorn app.main:app --reload
```
