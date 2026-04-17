# M8 — Projects (thin collaboration slice)

**Status:** in progress (research pre-code)
**Owner:** Kevin
**Last updated:** 2026-04-17

---

## Question

What's the smallest multi-user collaboration feature that ships
end-to-end on top of M7 auth — and what waits for a later slice?

### Sub-questions

- Is the first slice projects-only, projects-plus-roles, or
  projects-plus-invitations?
- How does a drawing carry both an owner *and* a project without
  the access model splintering?
- What's the migration path for drawings that already exist under
  a single user (M7 default)?
- How do M6 annotations pick up author identity now that users
  exist?
- What deliberately waits until M8.1 / M8.2?

## Why this matters

Opens **D-14** (M8 slice), **D-15** (flat vs. role-based
membership), **D-16** (drawing ↔ project FK shape), **D-17**
(annotation author attribution). Determines the first shared-state
primitive in Atlas. Get it wrong and every later collaboration
feature inherits the mismatch.

---

## Position

Opinionated. Each section ends with a decision.

### 1. Slice: projects + flat membership + optional drawing assignment

The original brief folds projects, roles, invitations, and
collaboration workflows. Same pushback as M7 applies: that's
three distinct surfaces fused into one milestone. Split them:

| M    | Scope                                                    | Depends on |
|------|----------------------------------------------------------|------------|
| **M8** | Project entity, flat membership (add-by-user-id), optional drawing-in-project | M7 |
| M8.1 | Invitations flow (email-based) + role system (admin/member/viewer) | M8 + M7.1 |
| M8.2 | Transfer-ownership + project-wide delete / archive        | M8 |
| M9   | OAuth (additive auth methods)                             | M7 |
| M10  | Share links (public read-only scoped tokens)              | M7 |

**Decision: M8 = Project entity + flat membership + nullable
project_id on drawings.** Roles, invitations, presence, activity
feeds all defer. Add-member-by-user-id is the primitive that
invitations later wrap; the invitation flow is a UX shell around
it, not a new data model.

### 2. Primary user story

"I'm an architect on a project with two colleagues. I want to
create a shared workspace, add the two of them by user ID (or
email they've already registered with), assign a few of my
drawings to the workspace, and have all three of us be able to
read, ask questions about, and annotate those drawings."

**In scope:** project creation + member management by user id,
drawing assignment/unassignment, shared read + write of project
drawings, author attribution on new annotations.

**Out of scope for M8:**

- Roles — everyone in a project is equal. *M8.1.*
- Email-based invitations. *M8.1 (depends on M7.1 email infra).*
- Project deletion / archive. *M8.2.*
- Transfer ownership between users. *M8.2.*
- Project-level chat / activity feed / presence.
- Per-project billing / quotas.
- Cross-project search.
- Migrating existing annotations to carry author_user_id
  retroactively (only new annotations get the attribution).

### 3. Data model (D-15, D-16, D-17)

Two new tables + one column on `drawings` + one column on
`annotations`.

```sql
projects
  id                UUID PK
  name              VARCHAR(120)  NOT NULL  CHECK length 1..120
  description       VARCHAR(2000) NULL
  created_by        UUID NOT NULL  REFERENCES users(id) ON DELETE RESTRICT
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()

INDEX projects(created_by)

project_members
  project_id        UUID NOT NULL  REFERENCES projects(id) ON DELETE CASCADE
  user_id           UUID NOT NULL  REFERENCES users(id) ON DELETE RESTRICT
  joined_at         TIMESTAMPTZ NOT NULL DEFAULT now()
  PRIMARY KEY (project_id, user_id)

INDEX project_members(user_id)        -- for "my projects"

ALTER TABLE drawings
  ADD COLUMN project_id UUID NULL
    REFERENCES projects(id) ON DELETE SET NULL;
  -- SET NULL (not CASCADE): deleting a project disassociates its
  -- drawings but leaves them owned by their creators. Deleting
  -- user data on a project-level delete is out of scope for M8.

CREATE INDEX ix_drawings_project_id ON drawings(project_id);

ALTER TABLE annotations
  ADD COLUMN author_user_id UUID NULL
    REFERENCES users(id) ON DELETE SET NULL;
  -- Nullable: pre-M8 annotations have no user attached.
  -- SET NULL on user delete keeps the note readable but drops the
  -- linked identity (GDPR-compliant-ish).
CREATE INDEX ix_annotations_author_user_id ON annotations(author_user_id);
```

**Design decisions:**

- **Drawings carry both `owner_id` AND `project_id`.** Creator
  stays recorded; project is an additional sharing scope. The
  alternative (exclusive — you're either personal OR in a project)
  loses authorship when you move a personal drawing into a team
  workspace. Bad trade.
- **`project_members` is flat — no `role` column.** Role system
  lives in M8.1. The row-exists-means-member invariant is exactly
  what M8.1 will extend with `role` rather than replace.
- **No invitation table.** You add an already-registered user by
  their ID (or email, which the service resolves to an ID). The
  invitation *flow* — "I sent Alice an email before she had an
  account" — lands in M8.1 once email infra exists.
- **`created_by` FK is RESTRICT.** A user who created projects
  can't be deleted until those projects are transferred or
  deleted (M8.2). Loud failure beats silent orphan.

### 4. Access rules

Updated from M7:

| Action               | Pre-M8 rule                                  | M8 rule |
|----------------------|----------------------------------------------|---------|
| Read drawing         | `owner_id = self OR owner_id IS NULL`        | M7 rule **OR** `project_id IS NOT NULL AND self ∈ members(project)` |
| Write drawing        | `owner_id = self`                            | M7 rule **OR** `project_id IS NOT NULL AND self ∈ members(project)` |
| Assign drawing → project | — | caller must own the drawing AND be a member of the target project |
| Unassign drawing from project | — | caller must own the drawing (regardless of project membership — you can always remove your own drawing from a project) |
| Claim unclaimed      | M7 rule                                      | M7 rule (unchanged) |
| Project membership   | —                                            | any member can add / remove members (flat; M8.1 adds role gates) |

Authoring rules:

- New annotations created by an authenticated user set
  `author_user_id = current_user.id`. `author_name` defaults to
  `current_user.display_name` if not supplied.
- Existing annotations (pre-M8) keep `author_user_id = NULL`; no
  backfill.

### 5. API surface

```
POST   /projects                        {name, description?}  → 201 ProjectOut (creator auto-added as member)
GET    /projects                        query: ?created_by_me=true  → list of ProjectOut
GET    /projects/{id}                                              → ProjectOut with members[]
PATCH  /projects/{id}                   {name?, description?}      → 200 ProjectOut  (any member)

POST   /projects/{id}/members           {user_id} OR {email}       → 201 MemberOut
DELETE /projects/{id}/members/{user_id}                            → 204  (anyone may remove anyone in v1; document the limitation loudly)

PATCH  /drawings/{id}/project           {project_id | null}        → 200 DrawingSummary
  - ownership required to assign
  - ownership required to unassign
  - setting project_id also requires membership in the target project
```

Response shapes (simplified):

```json
// ProjectOut
{
  "id": "uuid", "name": "...", "description": "...",
  "created_by": "uuid", "created_at": "...", "updated_at": "...",
  "member_count": 3,
  "drawing_count": 5,
  "members": [ { "user_id": "uuid", "email": "...", "display_name": "...", "joined_at": "..." } ]
}

// MemberOut
{ "user_id": "uuid", "email": "...", "display_name": "...", "joined_at": "..." }
```

No pagination on projects / members / drawings in v1 — tight
caps on each (≤ 100 members per project is a soft guardrail the
service enforces; ≤ 100 projects per user; past these we add
cursor pagination).

### 6. Migration strategy (existing data)

Atlas currently has **no production drawings that were created
under M7 auth** (the repo just shipped M7 on a branch; nothing is
merged to main). So the migration story is simple:

- Drawings without `owner_id` (legacy pre-M7 from dev DBs) stay
  unclaimed; the M7 claim flow handles them.
- Drawings with `owner_id` = Some User stay personal unless the
  owner explicitly assigns them to a project via `PATCH
  /drawings/{id}/project`.
- Annotations created pre-M8 have `author_user_id = NULL` —
  surfaced in the response as "author unknown" along with the
  free-text `author_name`.

No bulk-assignment script. No forced migration. The transition
is entirely voluntary, user-initiated, drawing-by-drawing.

### 7. Evaluation / acceptance

Pure pytest + Postgres + Redis (for auth sessions). No Claude,
no geometry.

Seed test set (~25):

**Projects CRUD (5):**
- POST creates project, creator is auto-member, row visible.
- GET lists my projects (I see projects where I'm a member).
- GET detail returns members + counts.
- PATCH name by a member → 200.
- PATCH by non-member → 404.

**Membership (5):**
- POST /members by user_id → 201; GET detail shows them.
- POST /members by email → resolves to user_id; → 201.
- POST /members with unknown user → 404.
- DELETE /members/{id} → 204; target user's subsequent
  `GET /projects/{id}` → 404.
- POST /members when caller isn't a member → 404.

**Drawing-project assignment (6):**
- PATCH /drawings/{id}/project by owner → 200; drawing visible
  to other project members.
- PATCH by non-owner → 404.
- PATCH to a project you're not a member of → 403.
- PATCH with `project_id=null` (unassign) → 200; other members
  lose read.
- Member-of-project-but-not-drawing-owner can read the project
  drawing.
- Member-of-project-but-not-drawing-owner can annotate and
  ask questions.

**Access (4):**
- Anon still 401 on everything.
- Non-member can't read project drawings.
- Non-member can't read project (project detail 404).
- Drawing not assigned to a project stays strictly owner-only.

**Annotations author attribution (3):**
- New annotation from user A shows `author_user_id = A`.
- Pre-M8 annotation (seeded with NULL author_user_id) still
  readable; response echoes null + `author_name` string.
- author_name defaults to user.display_name when body omits it.

**Integration (2):**
- M5 `POST /drawings/{id}/ask` works for a project-member non-owner.
- M6 annotation CRUD works for a project-member non-owner.

Acceptance for merging:

- [ ] Migrations (two: projects + drawings.project_id + annotations.author_user_id) run up + down cleanly.
- [ ] All 156 existing API tests pass unchanged.
- [ ] New 25-ish tests pass.
- [ ] No endpoint lets a non-member read a project drawing.
- [ ] Pre-M8 annotations stay readable (null author_user_id
  doesn't break serialization).

### 8. Delivery surface

**API first, no UI.** The frontend debt now covers five pending
slices (M5b chat, M6b annotations-on-viewer, M7b login page, M8b
project list / member management UI, and the drawing-to-project
picker). A single consolidation slice — "atlas-web Phase 2" —
should land after M8 API is solid, not five small UI efforts.

### 9. Risk assessment

#### 9.1 M4 Phase 3 still blocked

Same as M5/M6/M7: extraction is validated on synthetics only.
Real-drawing accuracy is unknown. M8 makes this visible to more
users at once (project members see the same extraction output),
so bad extraction fails louder. Good incentive to close Phase 3.

#### 9.2 UI debt keeps growing

M5b + M6b + M7b + M8b + drawing-assignment UI all deferred. The
consolidation slice gets bigger with every API milestone. Don't
defer it again past M8.

#### 9.3 Flat membership is a known hazard

Without roles, *any* member can add anyone to the project and
*any* member can remove anyone else, including the creator. This
is safe for a trusted small team (e.g., two architects working
together, pre-selected). It is *not* safe for a mixed-trust
context (firm + client + contractor). The M8.1 role system is
how we restore the obvious guardrails.

**Mitigation:** API responses for `GET /projects/{id}` include a
`warnings` field that flips on a `flat_membership` flag. UIs
should surface it ("any member can add or remove other members
— add roles in an upgraded plan / later milestone"). A
deployment cannot advertise "shared project" as a feature
without this caveat being visible.

#### 9.4 Adding members by email has a soft enumeration surface

`POST /members {email: "alice@..."}` returns 404 when Alice
doesn't exist. A malicious caller can check which emails are
registered. Not a showstopper (auth also has rate limits), but
worth a note: we should rate-limit the member-add endpoint
similarly to login. 10 attempts per (project, minute) is
generous enough for real use and tight enough to deter
enumeration.

#### 9.5 No project deletion

A project accumulates drawings and annotations that may become
stale. No way to archive or delete a project in M8. Deliberate —
deletion with N drawings spanning M members touches too many FK
behaviors. **M8.2** handles it.

#### 9.6 Drawing-move race

Two members simultaneously assign the same drawing to different
projects. The second wins by last-write. We use a simple
`UPDATE ... WHERE owner_id = :user` with no version check, so
no conflict detection in M8. For concurrent edits on the same
drawing this is fine (both are authorized); for "who moved my
drawing" a future audit log can help. Out of scope now.

## Implications for Atlas

- **New migration:** `0006_projects.py` (Alembic). Creates
  `projects`, `project_members`; adds `project_id` to `drawings`
  and `author_user_id` to `annotations`.
- **New models:** `Project`, `ProjectMember` in `atlas-db`.
  `Drawing.project_id` + `Annotation.author_user_id` columns
  added to existing models.
- **New services:** `apps/api/app/services/projects.py` —
  create/list/detail/patch, membership add/remove, drawing
  reassignment.
- **New routes:** `apps/api/app/routes/projects.py` — all of the
  above. Existing `annotations` POST handler updated to
  default `author_name` from current_user and record
  `author_user_id`.
- **Updated dependencies:** `owned_drawing_for_read/write` in
  `core/auth_dep.py` extends its access check to include project
  membership. One surgical edit that every existing endpoint
  inherits for free.
- **Updated conftest:** `_seed_project` helper, new `anon_client`
  isn't strictly needed (M7 fixtures cover it); add
  `test_other_user` fixture for multi-user tests.
- **HANDOFF update:** M8 row flips to in-progress; M8.1 / M8.2
  rows stay `planned` with the dependency arrows intact.

## Open follow-ups

- **M8.1 invitations + roles.** Depends on M7.1 email infra for
  the invitation half. The role half can land independently.
- **M8.2 delete + transfer.** Project deletion semantics, owner
  transfer on drawings, member-removal-with-data-retention story.
- **Cross-drawing / cross-project queries.** M5 Q&A today is
  single-drawing; a "find all rooms across my projects" is its
  own milestone.
- **Audit log.** Who added whom, who moved what. Table + query
  endpoint; small but its own slice.
- **Per-project LLM context.** Future M5 upgrade — Q&A across
  *every drawing in a project*. Needs careful context-window
  budgeting; belongs after M8b UI proves the single-drawing Q&A.

## Decision log entries to open

- **D-14 — M8 slice = Project entity + flat membership + optional
  drawing assignment.** Roles, invitations, delete, transfer all
  defer to M8.1+.
- **D-15 — `project_members` is flat (no role column) in v1.**
  Row existence = member. M8.1 extends with a role column.
- **D-16 — Drawings carry both `owner_id` and optional
  `project_id`.** Creator attribution persists when a drawing
  moves to a shared project.
- **D-17 — Annotations gain nullable `author_user_id`.**
  New annotations populate it from `current_user`; pre-M8 rows
  stay NULL (no backfill).
