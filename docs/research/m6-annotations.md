# M6 — Element annotations (thin review slice)

**Status:** in progress (research pre-code)
**Owner:** Kevin
**Last updated:** 2026-04-17

---

## Question

What's the smallest review-workspace feature that ships end-to-end
on top of M1–M5 without pulling in auth, projects, or threading —
and what deliberately waits until later milestones?

### Sub-questions

- Which of three candidate slices gives the highest value at the
  lowest risk — element annotations, export-only review, or
  read-only share links?
- What's the minimum data-model extension needed?
- How do annotations interact with the existing M5 citation surface
  and with re-extraction (D-05's immutable source runs)?
- What's the eval/acceptance bar without an auth system to lean on?
- What are the M5b (UI) and M4 Phase 3 (validation) implications?

## Why this matters

Opens **D-09** (M6 first slice) and **D-10** (annotation lifecycle
under re-extraction). Determines: the first review-workspace table
on the schema, the first "write" API that isn't extraction output,
and the precedent for how user-generated data attaches to
extractor-produced data. Get this wrong and every later
collaboration feature inherits the mismatch.

---

## Position

Opinionated. Each section ends with a decision.

### 1. Pick the slice: element annotations

**Decision: element annotations** (Option A in the prior
conversation).

Candidates considered:

| Option                      | Cost  | Value            | Advances M6 framing? |
|-----------------------------|-------|------------------|----------------------|
| **A: Element annotations**  | 1 table, CRUD endpoints, FK on Element | High — directly supports "review" workflow, hooks M5 citations | Yes — *review workspace* matches |
| B: Export-only review       | No new table; PDF/XLSX renderer | Medium — useful for hand-offs but doesn't enable interactive review | Partial — "exports" was in M6 scope but adds no interaction |
| C: Read-only share links    | 1 token table; new auth-adjacent primitive | Medium — unblocks sharing but not review itself | No — this is M7 (team collaboration) material |

**Why A wins:**

- Natural continuation of M5: the citation chips in an AskResponse
  become *addressable targets* for an annotation. "Show me the
  largest room → add a note 'confirm with structural'." The data
  flow from Q&A to annotation lands without extra scaffolding.
- Single-user value even pre-auth. A solo architect reviewing
  their own extraction benefits today; a team with auth benefits
  later. No option has this property.
- Data model is *additive*, not invasive. One new table with FKs
  to existing ones. No touching `Element`, `Drawing`, `Sheet`,
  `ElementSource`.
- Export-only (B) is a format shift of M3 takeoffs — doesn't move
  any *capability* forward. Defer until we want a specific export
  format for a real customer ask.
- Share links (C) are a collaboration primitive masquerading as
  review. They belong alongside auth in M7.

### 2. Primary user story

"I ran extraction and Q&A on a drawing. I want to flag element X
(a wall, a door, a room) with a short note so I remember to
revisit it later, and I want to retrieve all my notes as a list."

Out of scope for M6:

- Threading / replies (one-note-per-target only).
- Resolved / open state.
- @mentions, assignees.
- Per-sheet annotations without an element (deferred — adds a
  nullable-target case that bloats validation).
- Attachment files (image uploads).
- Rich text / markdown in the body (plain-text only).
- Notifications.
- Presence / real-time collaboration.

### 3. Data model

One new table: `annotations`.

```
annotations
  id              UUID PK
  drawing_id      UUID FK → drawings.id   NOT NULL  (denormalized; see below)
  element_id      UUID FK → elements.id   NOT NULL
  author_name     TEXT                    NOT NULL  CHECK length 1..120
  body            TEXT                    NOT NULL  CHECK length 1..4000
  created_at      TIMESTAMPTZ             NOT NULL  DEFAULT now()
  updated_at      TIMESTAMPTZ             NOT NULL  DEFAULT now()

INDEX annotations(drawing_id, created_at DESC)
INDEX annotations(element_id)

FK:
  - drawing_id → drawings.id  ON DELETE CASCADE
  - element_id → elements.id  ON DELETE RESTRICT
    (elements get deleted when a source is re-run w/ the same id,
     which our D-05 immutable-source model prevents; RESTRICT
     surfaces the invariant loudly if it ever breaks.)
```

Design decisions:

- **`drawing_id` is denormalized.** The dominant query is "every
  annotation on this drawing" (review UI). Joining through
  elements → sheet → drawing on each read is fine but the index
  shape is more forgiving with a direct FK.
- **`element_id` is required.** No "drawing-level" or
  "sheet-level" notes in v1. A user who wants that can annotate
  any element as a proxy, or we add it in M6b. Keeping the
  constraint strict avoids the nullable-target validation tree.
- **No `author_id`.** No auth → no users. `author_name` is a free
  string the client sends. When auth lands in M7, we add
  `author_id` + make `author_name` a legacy cache or drop it.
- **No `source_id` FK.** Annotations point at the element, not at
  the extraction run. See **D-10** below for the re-extraction
  consequences.

### 4. Re-extraction behavior (D-10)

**Decision.** Annotations are *extractor-run agnostic* in v1.

Consequences:

- Re-running extraction on a drawing inserts new Element rows under
  a new `ElementSource` row. The old source's elements are not
  deleted (per D-05 immutable sources).
- Old annotations keep pointing at the *old source's* element IDs.
  They don't automatically migrate to the "same" element in the
  new run — because we have no identity mapping between runs yet.
- The UI can surface this: "This annotation was made on the
  extraction from {date}. The current extraction is newer."
- A future milestone can add `element_identity` (stable cross-run
  IDs based on geometry hash or NCS layer + position) and migrate
  annotations.

**Rejected alternatives:**

- *Cascade-delete on source change.* Loses user work silently.
  Unacceptable.
- *Auto-migrate by bbox/kind match.* False-positives in real
  drawings; out of scope without an identity model.

### 5. API contract

```
POST /drawings/{drawing_id}/annotations
  body: { element_id, author_name, body }
  → 201 AnnotationOut
  → 400 element_mismatch if element_id isn't on this drawing
  → 404 not_found if drawing_id doesn't exist
  → 422 validation if body fields are empty / too long

GET  /drawings/{drawing_id}/annotations
  query: ?element_id=UUID (optional)
  → 200 { drawing_id, annotations: [AnnotationOut] }  (sorted newest first)

GET  /elements/{element_id}/annotations
  → 200 { element_id, annotations: [AnnotationOut] }

PATCH /annotations/{id}
  body: { body?: string, author_name?: string }
  → 200 AnnotationOut
  → 404 not_found

DELETE /annotations/{id}
  → 204
  → 404 not_found
```

Response shape:

```json
{
  "id": "uuid",
  "drawing_id": "uuid",
  "element_id": "uuid",
  "author_name": "Kevin",
  "body": "Confirm with structural.",
  "created_at": "2026-04-18T12:00:00Z",
  "updated_at": "2026-04-18T12:00:00Z"
}
```

Notes:

- No pagination in v1. If review-heavy usage surfaces >1k
  annotations on one drawing we'll add `?limit=&cursor=` later.
- `PATCH` is optional-for-v1 but cheap; include it so the contract
  doesn't have to grow in M6.1.
- Dependency route (`/elements/{id}/annotations`) is a convenience
  for the UI; it re-uses the same service call.

### 6. Evaluation / acceptance

No Claude, no geometry — pure CRUD against Postgres. Pytest-style
only.

Seed test set (~15):

- POST with valid element → 201, response shape matches, row in DB.
- POST with element that doesn't belong to this drawing → 400.
- POST with empty body → 422.
- POST with body over 4000 chars → 422.
- POST to missing drawing → 404.
- GET all for a drawing → ordered newest-first, correct count.
- GET filtered by element_id → only matching ones.
- GET by element → works from the convenience route.
- PATCH body → updates body + updated_at, not created_at.
- PATCH missing id → 404.
- DELETE → 204 + row gone.
- DELETE missing → 404.
- Delete parent drawing → annotations cascade-deleted (integration
  test, exercises the FK).
- Concurrent create on same element → both succeed (no unique
  constraint on element_id).
- Very long author_name boundary → 120 ok, 121 rejected.

Acceptance for merging:

- [ ] Migration runs both up and down cleanly.
- [ ] All endpoints return documented shapes.
- [ ] FK cascade verified in integration test.
- [ ] No cross-drawing leakage (an annotation on drawing A
  doesn't appear in drawing B's list).
- [ ] Existing 118 API tests still pass.

### 7. Delivery surface

**API first, no UI.** Same pattern as M5.

A UI slice (**M6b**) lands later: annotation chips rendered on the
sheet viewer at the cited bbox, inline "add note" when a user
clicks an M5 citation. That work *shares* the viewer-overlay
primitive M5b needs, so the order is:

1. (this milestone) M6 API.
2. M5b UI + M6b UI as one viewer slice — they use the same
   primitives (bbox anchoring, citation chips), so building them
   in sequence means one viewer build, not two.

### 8. Risk assessment

#### 8.1. M5b UI gap

The M5 research doc deferred the Q&A UI ("chat panel + citation
bbox linking") to M5b. Shipping M6 before M5b means:

- Atlas still has no user-facing chat interface when M6 API lands.
- The marketing framing ("natural-language Q&A", "intelligent
  building advisor") remains API-only. Demos depend on curl or
  the web UI being built.
- This is tolerable because the M6 API is self-contained and
  exercisable via pytest + curl; the UI work consolidates later.

**Recommendation in this doc:** don't ship any M6/M5b UI until
*both* APIs are solid. Then build the viewer overlay once, with
annotation chips + citation chips sharing the anchoring code.

#### 8.2. M4 Phase 3 blocker

Annotations point at elements. If extraction missed or
mis-classified elements on a real drawing:

- Users may annotate a wall the extractor mis-classified as a door
  — the note contaminates the wrong element.
- Users can't annotate something that wasn't extracted. No
  signal-to-user that a note *should* exist here.
- Re-extraction on better data produces new element IDs; old
  annotations keep pointing at the old run (per D-10).

Mitigations in the M6 design:

- The annotation response inherits the cited element's
  `extraction_status: "unvalidated_on_real_drawings"` flag (via a
  new field `meta.element_extraction_status` that reads from the
  source's status).
- The response echoes the cited element's `confidence` so the UI
  can show "annotated on element with 0.6 confidence — extractor
  was unsure about this one."

**Hard gate:** same as M5 — public-facing deployment of M6
waits on Phase 3 validation. Internal/synthetic use is fine.

#### 8.3. No-auth implications

Documented explicitly because this *will* catch someone:

- Any client can DELETE any annotation. No ownership check.
- `author_name` is a free string; anyone can claim to be anyone.
- No rate limiting; if the API is exposed publicly without a proxy
  layer, an attacker can spam arbitrary annotations.
- `updated_at` reflects last write, not who wrote — no audit.

**Gating:** M6 API is safe for:

- Local dev.
- Internal demos behind a VPN.
- Single-user self-hosted deployments.

M6 API is **not safe** for public SaaS release. Auth milestone
(M7) must land before any public-facing deployment includes write
endpoints.

## Implications for Atlas

- **New migration:** `0003_add_annotations.py` (Alembic). Numbered
  next after whatever the current head is — verify before writing.
- **New model:** `Annotation` in `atlas-db/atlas_db/models.py`.
- **New service:** `apps/api/app/services/annotations.py` — the
  usual pure-ish helpers the route calls.
- **New route:** `apps/api/app/routes/annotations.py`, plus a
  `/elements/{id}/annotations` GET on the existing
  `apps/api/app/routes/elements.py` (one extra method, reuses the
  service).
- **New tests:** `apps/api/tests/test_annotations_api.py` and
  `test_annotations_service.py`.
- **No new external deps.** SQLAlchemy + Pydantic already cover it.
- **HANDOFF update:** milestone table M6 row moves from `planned`
  to `in progress`, note the "thin slice" scope.

## Open follow-ups

- **Threading.** `parent_id` self-FK; "resolve" state. Fits
  naturally in M6.1 once the base table is live.
- **Attachments.** Image / PDF uploads on an annotation. Requires
  S3 key management similar to the drawing upload flow.
- **@mentions + notifications.** Needs auth; lives with M7.
- **Export integration.** A takeoff export that includes open
  annotations alongside element counts. Layered on when export
  lands as its own slice.
- **Element identity across runs.** A stable cross-source ID for
  elements (geometry hash, NCS signature). Unblocks annotation
  migration on re-extraction. Separate research note when we need
  it; not a pre-M6 blocker.

## Decision log entries to open

- **D-09 — M6 first slice = element annotations.** Scope, data
  model, and acceptance criteria as documented here. Status:
  decided by this note, awaiting user confirmation.
- **D-10 — Annotations are run-agnostic.** Annotations attach to
  `element_id` with no automatic migration across re-extraction.
  Documented consequence; can revisit when element-identity work
  lands. Status: decided by this note.
