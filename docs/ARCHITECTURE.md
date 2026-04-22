# Atlas — Architecture (start of V2)

A fast orientation for a new engineer (or Claude Code session) at the start of the V2 homeowner/tenant build. Read `docs/product-vision.md` first — that explains *what* we're building. This explains *how the code is laid out today*. Expect ~5 minutes.

## Top-level layout

Monorepo at `/opt/atlas`. Python services share a workspace; the web app is a separate Node project.

```
/opt/atlas
├── apps/
│   ├── api/          FastAPI HTTP service
│   ├── worker/       async extraction / reconstruction jobs
│   └── web/          Next.js 14 app (app router)
├── packages/
│   ├── atlas-core/   geometry + data model (framework-free Python)
│   └── atlas-db/     SQLAlchemy ORM models + Alembic migrations live under apps/api/app/migrations
├── docs/             product-vision.md, ARCHITECTURE.md, research/
├── infra/            Docker, Caddy, config
├── scripts/          seed_demo_account.py, generate_sample_dxf.py, init_test_db.py, eval_extraction.py
├── tests/            repo-level harness (harness_safety.py)
├── docker-compose.yml   dev stack (postgres, redis, minio, api, worker, web)
└── HANDOFF.md        legacy session-handoff notes (pre-v2; kept for history)
```

## Packages

- **`atlas-core`** — pure Python, no framework imports. The geometry + data model that every other service depends on.
  - `models.py` — Pydantic data classes (StructuredSheet, Wall, Door, Window, Room, …).
  - `geometry.py` — polylines, rings, intersection primitives.
  - `connectivity.py` — room-to-room adjacency graph.
  - `reconstruct3d.py` — 2D `StructuredSheet` → 3D `Scene3D` (wall volumes, openings, floor/ceiling). Uses `manifold3d` for boolean operations.
  - `enums.py`, `ingest.py`.
- **`atlas-db`** — SQLAlchemy ORM models in `models.py` (User, Drawing, Sheet, Element, ElementSource, Project, ProjectMember, Annotation, Tile). Source of truth for the DB schema; Alembic migrations live in `apps/api/app/migrations/versions/`.

## Services

- **`apps/api`** — FastAPI. Routes under `apps/api/app/routes/`: `auth`, `drawings`, `sheets`, `elements`, `extractions`, `annotations`, `connectivity`, `takeoffs`, `qa`, `model3d`, `projects`, `health`, `websocket`. Session-cookie auth (`atlas_session` HttpOnly + `atlas_csrf` readable). Rate limiting + structured error envelopes in `core/errors.py`. Runs at `:8000` in dev.
- **`apps/worker`** — long-running job runner. Consumes jobs off Redis, emits progress events back via `worker/events.py`.
  - `jobs/ingest.py` — PDF raster + tile pipeline.
  - `jobs/extract.py` — DXF → `StructuredSheet`.
  - `extractors/` — DXF, NCS layer classification, geometry helpers, validation.
  - `pipeline/` — shared PDF / raster / tile utilities.
- **`apps/web`** — Next.js 14 app-router. Protected area under `app/(protected)/{drawings,projects,me}`. Client talks to FastAPI through same-origin proxy via `lib/api.ts` (client) + `lib/api-server.ts` (SSR). Three.js viewer components in `components/viewer/`.

## Key components (where to look first)

| Concept                               | File                                                                              |
|---------------------------------------|-----------------------------------------------------------------------------------|
| Central data model for a drawing sheet| `packages/atlas-core/atlas_core/models.py::StructuredSheet`                       |
| 2D → 3D reconstruction                 | `packages/atlas-core/atlas_core/reconstruct3d.py::reconstruct_sheet`              |
| Three.js viewer (orbit + pitch-unified)| `apps/web/components/viewer/Model3DCanvas.tsx`                                    |
| Scene JSON API endpoint               | `GET /drawings/{id}/sheets/{id}/model3d` — `apps/api/app/routes/model3d.py`       |
| Demo entry point                      | `POST /auth/demo-login` — `apps/api/app/routes/auth.py`                           |
| DXF extractor                         | `apps/worker/worker/extractors/dxf.py` (invoked from `jobs/extract.py`)           |
| Session + CSRF cookies                | `apps/api/app/core/sessions.py`                                                   |
| Demo account + seed data              | `scripts/seed_demo_account.py`                                                    |

## What V2 keeps (no rewrite)

- Geometry engine (`atlas-core`) — `StructuredSheet` and friends. Source-agnostic; works equally for DXF-extracted and AI-generated input.
- 3D viewer (`Model3DCanvas`) — Three.js orbit + pitch-unified dollhouse/floor-plan mode, SSAO, outline post-processing, HUD.
- API scaffolding — auth, sessions, rate limiting, error envelopes, websocket progress stream.
- Demo mode — `POST /auth/demo-login`, `scripts/seed_demo_account.py`, four demo DXFs (bungalow, apartment, office, retail).
- Test harness safety — `tests/harness_safety.py` + `apps/api/tests/test_harness_safety.py`. Sentinel-row protection and DB-name checks keep tests off live data.
- DXF extraction pipeline — remains the "upload existing drawings" path for V2's Grounds step.

## What V2 reframes (structure stays, framing changes)

- **Drawings list page** → **projects list page.** The backend already has `Project` as first-class (created_by, members, drawings-under-a-project). V2 repositions the projects list as the primary index; drawings become one of several inputs to a project. `apps/web/app/(protected)/projects/page.tsx` carries `TODO(v2)` headers covering copy + layout changes.
- **Q&A chat service** → **conversational design interface.** The M5 `/drawings/{id}/ask` endpoint + `ChatPanel` component stay; what changes is the system prompt, the set of tools the LLM can call, and the surface (from a sidebar on a drawing page to the front door of the app).
- **File-centric UX** → **project-centric UX.** Post-login entry becomes a conversational composer + project-type picker rather than a drawings table.

## What V2 deprecates (remove or hide)

- Architect-specific HUD chips in the 3D viewer (translator-stats badge, extractor confidence chips) — keep the data for diagnostics, remove from end-user surfaces.
- "Extractions" terminology in user-facing copy — homeowners don't know what an extraction is.
- Drawing-as-primary-unit mental model — the `/drawings` index can remain for upload-existing flows but is no longer a top-level nav surface.
- "Group drawings and share with collaborators" framing on `/projects` — V2 projects are one user × one undertaking.

## Conventions

**Python** — PEP 8, type hints required on public APIs. Pytest for tests. Ruff formats. Avoid mocking the DB in integration tests; the harness-safety layer makes real-DB tests safe (see `tests/harness_safety.py`).

**TypeScript** — `strict: true`. Server components for data fetch (`lib/api-server.ts`), client components for interactivity (`lib/api.ts`). Tailwind for styling; design tokens in `tailwind.config.ts` (`bg-base`, `text-primary`, `accent`, …). No inline hex colors.

**Commit messages** — conventional-commits style with scope where useful. Prefixes in rotation: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`. Scopes seen: `api`, `web`, `worker`, `core`, `fixtures`, `tests`. Examples from the log: `fix(web): 3D canvas above the fold in viewer`, `feat(core,worker): host walls for windows (parity with doors)`, `docs: Atlas product vision v2.0`.

**Branch naming** — `feature/<slug>` for multi-session feature series (current: `feature/v2-homeowner`). Pre-v2 milestone branches used `m{n}/<slug>` and `web/m{n}-<slug>`; that scheme is retired for V2 — one long-lived `feature/v2-homeowner` branch, merged into main in slices.

**Test harness safety** — every test suite that touches the DB must go through `tests/harness_safety.py`. Never mock the DB. `init_test_db.py` sets up `atlas_test` (DB name is checked at test start; a mismatch aborts). Do not skip, bypass, or weaken these guards — they exist because a prior incident leaked into `atlas` and took live data with it.

**Auth** — session cookie (`atlas_session`, HttpOnly, 24 h) + CSRF cookie (`atlas_csrf`, readable). All write endpoints require the CSRF header; reads don't. Demo account flow lives at `POST /auth/demo-login`.

## Historical notes

Sessions 1 through 3.5 built the infrastructure above against an earlier (architect-analytical) framing of Atlas. The V2.0 pivot changed the *product*, not the *infrastructure*. `HANDOFF.md` reflects the pre-pivot framing and is kept for reference only; `docs/product-vision.md` is canonical going forward.
