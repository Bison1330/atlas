# HANDOFF

Working doc for resuming work on Atlas across chat sessions. If you're a new Claude chat picking this up — read this top-to-bottom before touching the code.

Last updated: **2026-04-17** (end of M3).

---

## What Atlas is

An AEC platform for architectural drawing analysis. Tagline: **"Architecture that checks itself."** Ingests construction documents (PDFs, DWGs, BIM exports), lifts them into a structured representation, and reasons over them — coordination checks, design-intent review, Q&A with sheet citations.

## Where things live

- **Repo:** `git@github.com:Bison1330/atlas.git` (GitHub user: `Bison1330`)
- **Droplet working copy:** `/opt/atlas` (Ubuntu 24.04, Docker installed)
- **User:** Kevin — `khahn6030@gmail.com`
- **GitHub SSH key on the droplet:** `~/.ssh/id_ed25519` (label: `atlas-droplet-github`) — already authorized; `ssh -T git@github.com` succeeds as `Bison1330`.

## Milestones

| ID  | Title                | Status   | Notes                                 |
|-----|----------------------|----------|---------------------------------------|
| M0  | Foundation           | **live** | Monorepo, stack, CI/CD, skeletons     |
| M1  | Ingest pipeline      | **live** | PDF → sheets → tiles, frontend viewer |
| M2  | Structured drawings  | **live** | Rooms, walls, doors via NCS + ezdxf   |
| M3  | Enhanced analysis    | **live** | Takeoffs + room connectivity + eval framework (Tier 1 synthetic fixtures PASS; gap catalog for real-CAD limits in `docs/research/extractor-gaps.md`). Code checks + cost deferred — not in the shipped slice. |
| M4  | Real-CAD capability  | in progress | Branch `m4/real-cad-capability`. **Phase 1 shipped (`b70367d`):** G-R3 (INSERT blocks), G-C1 (window classification), G-R1 (SPLINE walls). **Phase 2 shipped:** G-O1 (explicit-vs-derived room dedup) and G-R5 (multi-segment polyline hosting). Remaining gaps in `docs/research/extractor-gaps.md` are post-MVP. |
| M5  | Design-intent Q&A    | planned  | Grounded answers with citations       |
| M6  | Review workspace     | planned  | Annotations, exports                  |
| M7  | Team collaboration   | planned  | Projects, roles                       |

Rule: **each milestone ships end-to-end before the next starts.**

### Running the extractor eval (fresh clone)

`scripts/eval_extraction.py` runs the M2 reader + M3 connectivity in-process against YAML ground-truth manifests. Deps are the worker's + atlas-core's + pyyaml — install into a venv:

```bash
python3 -m venv .venv-eval
.venv-eval/bin/pip install -e 'packages/atlas-core[dev]' -e 'apps/worker' pyyaml
.venv-eval/bin/python scripts/eval_extraction.py
```

Exits 0 iff every non-skipped fixture passes. Tier 2/3 manifests with no physical file SKIP by design (those files are gitignored; see `tests/fixtures/corpus/MANIFEST.md` for how to populate them).

---

## M0 — what was delivered

Commit `f717b8a` on `main` — 70 files, 2592 insertions.

### Layout

```
atlas/
├── apps/
│   ├── api/          FastAPI gateway
│   ├── worker/       RQ worker (default queue)
│   └── web/          Next.js 15 App Router frontend
├── packages/
│   └── atlas-core/   Shared Pydantic domain model
├── infra/
│   ├── Caddyfile     Reverse proxy + auto-TLS
│   └── scripts/      bootstrap-droplet.sh, deploy.sh, backup-postgres.sh
├── .github/workflows/
│   ├── test.yml      pytest + ruff + next build
│   └── build.yml     Multi-image GHCR push (atlas-api, atlas-worker, atlas-web)
├── docker-compose.yml         Local dev (includes MinIO)
├── docker-compose.prod.yml    Prod (real S3, GHCR images, Caddy)
└── .env.example
```

### Service details

**`apps/api`** (FastAPI 0.115+, Python 3.12)
- `/health` — liveness, no deps touched
- `/health/ready` — pings Postgres + Redis, 503 w/ per-dep detail on failure
- `structlog` for structured logging (JSON in prod, colored console in dev)
- Request-ID middleware (`X-Request-ID`) binds contextvars so every log line in a request is correlatable; duration logged on each request
- CORS from `CORS_ORIGINS` env var
- Sentry via `SENTRY_DSN` (starlette + fastapi integrations)
- Alembic configured with baseline migration `0001_baseline` (no tables yet — placeholder so future migrations have a parent)
- Tests: `apps/api/tests/test_health.py` — 4 passing (liveness, readiness ok, readiness 503, request-ID echo)

**`apps/worker`** (RQ 1.16+)
- Listens on `default` queue
- Same logging / Sentry pattern as API
- No jobs defined yet

**`apps/web`** (Next.js 15.1.3, React 19, Tailwind v3, TypeScript)
- Dark design system — tokens in `tailwind.config.ts`:
  - `bg.base` `#0B0D10`, `bg.surface` `#12151A`, `bg.elevated` `#1A1E24`
  - `border.subtle` `#242A32`
  - `text.primary` `#F2F4F7`, `text.secondary` `#B4BCC8`, `text.muted` `#7A8494`
  - `accent` `#3B82F6` (with `accent.dim` `#2563EB`) — switched from green to blue mid-M2
- Fonts: Inter (sans) + JetBrains Mono (mono) via `next/font/google`
- 8px spacing grid (spacing.1 = 8px, spacing.2 = 16px, …)
- Landing page is 5 sections: `Nav → Hero → Capabilities → Approach → Status → Footer`
- `output: "standalone"` — Dockerfile uses three-stage build ending at `node server.js`
- Icon: `app/icon.svg` (Next 15 file-based convention — do NOT re-add `favicon.ico`)

**`packages/atlas-core`** (Pydantic v2)
- Pure domain models, no runtime side effects
- Public API (from `atlas_core import …`):
  - `StructuredDrawing`, `StructuredSheet`, `DrawingElement`
  - `Room`, `Wall`, `Door`, `Window`, `GenericElement`
  - `Point`, `Polyline`, `Polygon`, `BoundingBox`
  - `ElementKind`, `SheetDiscipline`, `Units`
- `DrawingElement` is a discriminated union keyed on `kind`
- Tests: `packages/atlas-core/tests/test_models.py` — 3 passing

### Infra

- `infra/Caddyfile` fronts `api` at `/api/*` (path-stripped), proxies `/health` and `/health/ready` directly for uptime monitors, and catches everything else to `web:3000`. Auto-TLS via `ATLAS_DOMAIN` env var.
- `infra/scripts/bootstrap-droplet.sh` — idempotent fresh-droplet provision (Docker, firewall, data dirs, clone repo, `.env` stub).
- `infra/scripts/deploy.sh` — pulls GHCR images, `docker compose up -d`, runs `alembic upgrade head`, checks readiness.
- `infra/scripts/backup-postgres.sh` — daily `pg_dump | gzip | aws s3 cp`. Cron example in the script header.

### CI

- `test.yml` — on push/PR to main: three jobs (atlas-core, atlas-api, atlas-web) running ruff + pytest or typecheck + lint + build.
- `build.yml` — on push to main or `v*` tags: matrix builds `atlas-api`, `atlas-worker`, `atlas-web` Docker images and pushes to `ghcr.io/bison1330/<image>`. Uses `gha` cache per image.

---

## Conventions / decisions

These are the non-obvious calls — don't silently reverse them.

- **`atlas-core` stays dependency-light.** Only Pydantic. It gets imported by api, worker, and every future analyzer. Don't pull SQLAlchemy, httpx, boto3, etc. in here.
- **Healthcheck split.** `/health` must stay cheap (liveness probe). `/health/ready` is the one that touches deps. Don't collapse them.
- **Request-ID is `X-Request-ID`, not `X-Correlation-Id`.** It's echoed on responses and bound via `structlog.contextvars` so it shows up in every log line during the request.
- **Structured logging is structlog, not `logging` directly.** See `app/core/logging.py` / `worker/logging.py` — JSON in prod, console renderer in dev.
- **Sentry init is DSN-gated.** If `SENTRY_DSN` is unset, no init call is made. Don't wrap everything in `try/except ImportError` — the sdk is a hard dep.
- **Design tokens are the source of truth in `tailwind.config.ts`.** Don't hardcode hex values in components; use `text-accent`, `bg-bg-surface`, etc. The tokens above are the spec — changing them means updating the spec.
- **Next.js `output: "standalone"`** is non-negotiable for the prod Dockerfile to work (it copies `.next/standalone`). Don't remove it.
- **Alembic baseline is intentionally empty.** M0 has no tables. `0001_baseline` exists only as a versioning parent. M1+ migrations should stack on it.
- **Web ESLint is on.** A `'` in JSX copy failed the build during M0 verify — use `&apos;` (or wrap the string in `{"…"}`) rather than disabling the rule.
- **Prod compose uses GHCR images**, not local builds. `docker-compose.prod.yml` references `ghcr.io/bison1330/atlas-{api,worker,web}:${ATLAS_VERSION:-latest}`. Images are produced by `build.yml`.

---

## How to verify the stack still works

From `/opt/atlas` (or a fresh clone):

```bash
cp .env.example .env
docker compose build
docker compose up -d
sleep 10
curl -fsS http://localhost:8000/health          # → 200 {"status":"ok",...}
curl -fsS http://localhost:8000/health/ready    # → 200 {"status":"ready", checks: postgres+redis ok}
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:3000/   # → 200
docker compose down
```

At M0 end-of-build, all of the above passed. If a new session sees a regression, start there.

### Running tests without Docker

```bash
# atlas-core
pip install -e "packages/atlas-core[dev]"
pytest packages/atlas-core/tests -v

# api
pip install -e "apps/api[dev]"
cd apps/api && pytest -v
```

---

## Known loose ends / nice-to-haves

Not blockers for M1 but worth keeping in mind:

- No `ruff` config file at repo root — each `pyproject.toml` configures ruff independently. Fine, but if a root-level `ruff.toml` appears later, dedupe.
- `apps/web/.eslintrc.json` is minimal (`extends: next/core-web-vitals`). No custom rules yet.
- `docker-compose.prod.yml` references `/var/atlas/…` host paths for Postgres/Redis volumes. `bootstrap-droplet.sh` creates them. Any prod-side volume changes need both files updated.
- The web app has no runtime API wiring yet (landing page is static). `NEXT_PUBLIC_API_URL` is threaded through but unused — M1 is when it gets consumed.
- There's no `packages/atlas-core` published wheel; API/worker install it via local path in their Dockerfiles (`pip install /packages/atlas-core`). Fine for a monorepo; revisit if we need to ship it separately.

---

## Starting M1

M1 is **ingest pipeline: PDF → sheets → tiles**. Rough shape:

1. Add an `apps/api/app/routes/uploads.py` that accepts a PDF, stores it in S3 under `drawings/<id>/source.pdf`, and enqueues an ingest job on the `default` queue.
2. Add `apps/worker/worker/jobs/ingest.py` — rasterize each page, slice into tiles, upload to S3 under `drawings/<id>/tiles/…`, write a `drawings` row to Postgres.
3. SQLAlchemy models + the first real Alembic migration (`0002_drawings`).
4. A minimal upload UI in `apps/web`.

Don't start M1 work on `main` directly — branch off as `m1/ingest-pipeline`.
