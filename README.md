# Atlas

**Architecture that checks itself.**

Atlas is an AEC platform for architectural drawing analysis — a monorepo of services that ingest, structure, and reason over construction documents.

## Milestone 0 — Foundation

This milestone establishes the foundation: monorepo layout, local dev stack, CI/CD, and skeleton services with working healthchecks. No analysis yet — just the scaffolding everything else builds on.

## Layout

```
atlas/
├── apps/
│   ├── api/          FastAPI service (health, routing, middleware)
│   ├── worker/       RQ worker for async jobs
│   └── web/          Next.js 15 App Router frontend
├── packages/
│   └── atlas-core/   Shared Python domain model (drawings, rooms, walls…)
├── infra/
│   ├── Caddyfile     Reverse proxy + auto-TLS
│   └── scripts/      Droplet bootstrap, deploy, backup
├── docker-compose.yml       Local dev stack
└── docker-compose.prod.yml  Production stack (uses real S3)
```

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then:

- Web: <http://localhost:3000>
- API: <http://localhost:8000>
- API health: <http://localhost:8000/health>
- API readiness: <http://localhost:8000/health/ready>
- MinIO console: <http://localhost:9001> (atlas / atlas-secret)

## Stack

- **API:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg3
- **Worker:** RQ (Redis Queue)
- **Web:** Next.js 15, React 19, TypeScript, Tailwind CSS
- **Data:** Postgres 16, Redis 7, S3 (MinIO locally)
- **Observability:** structlog, Sentry
- **Proxy:** Caddy (auto-TLS in prod)

## CI

- `test.yml` — lint + tests for Python packages and web app on each push
- `build.yml` — builds and publishes Docker images to GHCR on `main`

## License

Proprietary — Atlas, © 2026.
