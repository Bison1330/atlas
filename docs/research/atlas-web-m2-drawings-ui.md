# atlas-web M2 — drawings list UI

**Status:** in progress (research pre-code)
**Owner:** Kevin
**Last updated:** 2026-04-17

---

## Question

What's the minimum shape of a `/drawings` landing page that gives
an authenticated user a legible list of their drawings — and what
backend work does it drag along?

### Sub-questions

- Is there a `GET /drawings` list endpoint today? If not, what's
  its shape — filter semantics, access rules, pagination?
- Should the list include project-shared drawings (per M8 access
  rules) or only owned ones?
- List vs grid layout for the UI — which reads better for
  architects scanning 5–50 drawings?
- What metadata is worth showing on each row (filename, sheet
  count, upload status, owner, project badge, etc.)?
- How does the new page integrate with existing `/upload` and
  `/drawings/[id]` routes without breaking them?
- Does the scope include thumbnails (requires S3 preview fetches)
  or defer to a later polish slice?

## Why this matters

Opens **D-19** (drawings list contract — API + UI). This is the
canonical way users get from "logged in" to "looking at a
drawing." Get the list shape wrong and every subsequent slice
(projects dashboard, upload flow polish, viewer entry points)
either inherits the mistake or has to work around it.

---

## Position

Opinionated.

### 1. Slice choice — "list + empty state only"

Same pushback pattern: the ask combined API + list UI + empty
state + thumbnails + filters. Each of those is its own decision.

**Decision: v1 is `GET /drawings` endpoint + `/drawings` list
page + empty state.** Thumbnails, filters, bulk actions,
pagination all defer. The list renders at most ~100 drawings —
beyond that we add cursor pagination in a follow-up.

In scope:
- New `GET /drawings` endpoint (API). Lists drawings the caller
  can read per the M7+M8 access rules (owned + unclaimed +
  project-member).
- New `/drawings` page (web). Authenticated-only (caught by M7
  middleware). Shows the list or the empty state.
- Metadata per row: filename, project name (if assigned), owner
  badge (you / project member), status, sheet count, last updated.
- Link to `/drawings/[id]` on row click. Link to `/upload` from
  a prominent header action.

Out of scope (each has a later home):
- Thumbnail previews — `web/m2b-drawings-thumbnails` (needs
  sheet-preview prefetch + lazy loading).
- Filter / sort / search — `web/m2c-drawings-filter`.
- Bulk actions (move to project, delete) — `web/m2d-drawings-bulk`.
- Pagination — only needed once >100 drawings is a plausible
  user state.
- Drawing rename — M1 doesn't expose an edit endpoint;
  `web/m2e-drawing-edit` pairs with an API change.

### 2. API: new `GET /drawings` endpoint (D-19-A)

**Decision:** one new route, `GET /drawings`, no query params in
v1. Returns drawings readable by the caller.

```
GET /drawings
  → 200 {
      count: N,
      drawings: [ DrawingListItem, ... ]
    }

DrawingListItem {
  id: UUID,
  source_filename: str,
  project_name: str | null,      # from drawings.project_name field
  project_id: UUID | null,       # M8 shared workspace (not the free-text field)
  is_owner: bool,                # owner_id == current_user.id
  owner_email: str | null,       # populated only when is_owner=false
  status: IngestStatus,          # queued / rasterizing / tiling / completed / failed
  progress_percent: int,
  page_count: int | null,
  size_bytes: int,
  created_at: datetime,
  updated_at: datetime,
}
```

**Ordering:** `created_at DESC` (newest first). No toggle in v1.

**Access filter** (reuses the M7 `drawing_readable_by` predicate
in aggregate form):

```sql
WHERE owner_id = :user_id
   OR (project_id IS NOT NULL AND project_id IN (
        SELECT project_id FROM project_members WHERE user_id = :user_id
   ))
   OR owner_id IS NULL           -- legacy/unclaimed; visible to all authed users
```

**Defaults to ~100 rows** (soft cap via `LIMIT 100`). If we ever
serve real multi-year portfolios with thousands of drawings, we
add pagination then.

**Why not extend the existing `/drawings/{id}` endpoint:** that's
a detail view; listing is a fundamentally different shape. Mixing
them would bloat the detail response.

**Why not a gRPC-style `/drawings:list`:** REST idioms win — a
new FastAPI route added to `apps/api/app/routes/drawings.py`
slots in next to the upload + detail handlers without schema
drift.

### 3. UI: list vs grid vs cards

Options considered:

| Layout | When it wins | When it loses |
|--------|--------------|---------------|
| **Dense list (table-like rows)** | Scannable at 10–50 drawings; metadata columns legible | Thumbnails feel cramped |
| Grid of cards | Thumbnail-forward; 3–12 drawings | Metadata gets buried; wastes space at scale |
| Two-pane (list + preview) | Long reference sessions | Over-engineered for v1 |

**Decision: dense list.** Atlas users scan drawings by filename
and metadata more than by visual identity — this is a project
tool, not a Pinterest board. When thumbnails land in the
follow-up slice, they fit as small ~60px inline previews on
existing rows without restructuring.

Row shape (desktop, 1200px width):

```
┌──────────────────────────────────────────────────────────────────────┐
│  FILENAME.pdf                            Status · 3 sheets · 2.4 MB  │
│  project: Hillside House · you · 2d ago                              │
└──────────────────────────────────────────────────────────────────────┘
```

Row is a link to `/drawings/{id}`. Hover lifts the background to
`bg-elevated`. Status is a colored dot + label matching the
existing M1 progress palette.

### 4. Empty state

Centered card inside the same list container, shown when `count
== 0`:

```
    You haven't uploaded any drawings yet.
         [ Upload your first drawing → ]
        Supported formats: PDF (M1). DXF
        extraction is a step after upload.
```

Design: reuses `AuthCard`-shaped container so the layout feels
consistent with /login/register. Primary button takes the user
to `/upload`.

If the user has zero owned drawings but *is* a member of projects
with shared drawings, we still show those — so the empty state
only fires when `count == 0` for real.

### 5. Integration with existing routes

- **`/upload`** — already exists. After upload, redirect to
  `/drawings/{new_id}` (existing behavior). Add a "Back to all
  drawings" link in the upload page header pointing at
  `/drawings`.
- **`/drawings/[id]`** — already exists. Add a back-link in its
  header to `/drawings`.
- **Nav "Open app"** — currently targets `/upload`. **Change to
  `/drawings`** so the primary entry into the app shows the
  list, and upload becomes a secondary action reachable from
  the list. Matches the pattern most document-management tools
  use.

### 6. Eval / acceptance

**Manual smoke (must pass before merge):**
- [ ] Authenticated user with 0 drawings visits `/drawings` →
  sees empty state + upload CTA.
- [ ] Authenticated user with N drawings (1, 5, 100) visits →
  sees list ordered newest-first.
- [ ] Click a row → lands on `/drawings/{id}` viewer.
- [ ] Click "Upload" CTA → lands on `/upload`.
- [ ] Anonymous visit → redirect to `/login?next=%2Fdrawings`
  (middleware handles this; already live after M7-auth-ui slice).
- [ ] User A's drawings don't appear in user B's list (access
  isolation).
- [ ] Drawing in a project the user is a member of appears with
  the right badge.

**Automated:**
- API: one pytest for `GET /drawings` covering empty, owned,
  project-shared, cross-user isolation.
- UI: defer until Playwright infra lands (still `atlas-web-m7`
  territory — no E2E yet).
- Unit: simple type-check on the DrawingListItem shape matching
  between API response and TS type.

### 7. Delivery surface

Single branch: `web/m2-drawings-ui`. Includes:
- API change: new route + service layer function.
- Web change: new page + updated Nav.

Merged as one `--no-ff` commit to main, same pattern as the
M4–M8 + atlas-web M7 merges. Rebuild after merge: `api` + `web`
containers.

### 8. Risk assessment

#### 8.1 The access-filter query isn't trivial

The `owner OR project-member OR unclaimed` predicate touches
three different tables (drawings, project_members, users) and is
easy to write subtly wrong — either leaking other users'
drawings or hiding the caller's own. Mitigation: the pytest
assertion for "cross-user isolation" is the critical one. Must
pass with at least two users + one project spanning them.

#### 8.2 Project-membership join scales poorly without pagination

The access query joins through `project_members` which at
realistic scale (dozens of projects, hundreds of members) is
still fine, but at 10k+ members the OR subquery gets slow. Not a
v1 concern; noted for when multi-tenancy hits the platform.

#### 8.3 "Project" field confusion

Atlas already has two "project" concepts:
- `drawings.project_name` — free-text field from M1 (per-drawing
  metadata typed at upload time; no FK).
- `drawings.project_id` — M8 shared workspace (nullable FK).

The list row should show *both* clearly when they differ. When
`project_name` exists but `project_id` is null, the drawing is
private-to-owner but tagged with project text. When
`project_id` is set, it's a shared workspace regardless of
`project_name`. Research flag: surface `project_id` as the
authoritative grouping; keep `project_name` as a secondary text
tag. A later migration may consolidate these.

#### 8.4 M4 Phase 3 gate still closed

Same as every M5+ slice: deploying a more-usable UI pulls the
rope closer to "real users actually trying Atlas." The
extraction still ships with the
`unvalidated_on_real_drawings` flag. Doesn't block this slice —
just restates the public-release gate.

## Implications for Atlas

- **API:** new route in `apps/api/app/routes/drawings.py`
  (`GET /drawings`), new helper in
  `apps/api/app/services/drawings.py` (the access-filter query).
  Pydantic `DrawingListItem` response model.
- **Web:** new `apps/web/app/(protected)/drawings/page.tsx` (the
  list) — note the existing `/drawings/[id]` must move under
  `(protected)/drawings/[id]/page.tsx` or we need the
  `(protected)` layout to wrap both.
- **Nav:** "Open app" target changes from `/upload` to
  `/drawings`.
- **Client SDK:** new `listDrawings()` in `lib/api.ts`.
- **Tests:** one pytest covering the 4 access cases; no UI tests
  until Playwright infra lands.

## Open follow-ups

- **web/m2b-drawings-thumbnails** — sheet-preview prefetch + lazy
  loading on the list rows.
- **web/m2c-drawings-filter** — search box + project filter.
- **web/m2d-drawings-bulk** — multi-select + bulk "move to
  project" action.
- **API pagination** — cursor-based (`?after=<uuid>&limit=N`).
- **Drawing rename / delete endpoints** — unrelated surface but
  needed eventually.

## Decision log entries to open

- **D-19-A — `GET /drawings` contract.** Lists readable drawings;
  newest first; soft cap 100; no filters in v1.
- **D-19-B — Drawings UI layout is dense list, not grid.** Row
  shape: filename + metadata line; link-on-click to viewer.
  Thumbnails, filters, bulk all deferred.
