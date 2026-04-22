# Atlas V1 — Kitchen Design System: Architecture Commitment (Session 0)

Status: committed 2026-04-22. Closes Session 0 per `docs/v1-kitchen-plan.md`.

This document pins the V1 kitchen system's technology choices, schema, API surface, frontend structure, integration points with existing Atlas code, LLM prompt skeletons, and testing strategy. It answers the three open questions from the plan (solver / render provider / jurisdictions) and registers six additional risks uncovered during research.

Read order going forward: `docs/product-vision.md` → `docs/v1-kitchen-plan.md` → this doc → `docs/v1-kitchen-status.md`.

---

## 1. Library choices with reasoning

### Constraint solver — Google OR-Tools CP-SAT

Apache 2.0, Python-native, `AddNoOverlap2D` is a first-class primitive for non-overlapping 2D rectangles on integer grids — which is exactly the shape of a kitchen layout problem on a 3-inch grid. Supports hard constraints and soft preferences via weighted objectives, so NKBA best-practice and code-required rules can coexist with different weights. Battle-tested (Google uses it in production), and every serious 2024–2025 floor-plan paper pairs a learned component with a hard-constraint repair layer — CP-SAT is the repair layer, optional learned prior comes later.

Alternatives considered: MiniZinc (no Python-native bindings at the level we need), Z3 (SMT is overkill and slower for pure geometry), custom solver (three months we don't have).

### LLM for intake — Claude Opus 4.7

Interview quality is the top lever on the whole pipeline: a bad brief guarantees bad layouts no matter how good the solver is. Opus's multi-turn reasoning and willingness to ask one-or-two targeted questions per turn (rather than a wall of prompts) is the behavior we need. Cost per interview (~15–25 turns) is acceptable at Opus pricing because it happens once per project.

### LLM for ranking — Claude Opus 4.7

Ranking is the other place quality dominates cost. The model reads 20+ validated candidate layouts, cross-references the user's brief, and produces top-3 with plain-English tradeoff explanations. This is architectural judgment, not a structured transform — Opus earns its cost here.

### LLM for constraint translation + refinement interpretation — Claude Sonnet 4.6

Both tasks are well-structured: take input JSON, produce output JSON. Faster and cheaper than Opus, and the schema-bound nature of the outputs makes quality indistinguishable from Opus in practice. Constraint translation runs once per project (brief + jurisdiction → ConstraintSet). Refinement interpretation runs every time the user types an edit, so latency matters.

### AI rendering — benchmark Flux Schnell vs SDXL+ControlNet in Session 7

Do not commit to one model yet. Flux Dev is off the table (non-commercial license). The two viable options are:

- **Flux Schnell** (Apache 2.0, ~$0.003/image, 4-step, lower quality) — cheapest, cleanest licensing, likely weaker on fine detail.
- **SDXL + ControlNet family** (~$0.005–0.015/image, deeper LoRA ecosystem) — more expensive per image, but more mature controllability for depth/edge/material conditioning.

Flux Pro is deferred; it requires commercial negotiation with Black Forest Labs, and we'd rather not block V1 on that.

ControlNet inputs will be: **depth map from the 3D scene + MLSD edges + per-material segmentation mask**. That's why per-surface material IDs are a day-one schema requirement — see §2.

Session 7 runs both on the same 50-brief acceptance set and commits to one based on quality gate pass rate.

### Rendering host — Replicate (V1), self-host at ~50K renders/month

Replicate gives us instant access to Schnell, SDXL, and the ControlNet family with no infra; acceptable latency; pay-per-render billing that won't explode until traction is real. Self-host migration (probably on RunPod or a dedicated GPU box) kicks in at ~50K/month when the per-render savings justify the ops burden. Alternative host to trial if Replicate is flaky: Fal.

### Cost data — Craftsman primary + BLS PPI adjustment + Remodeling Magazine calibration

- **Craftsman National Renovation & Insurance Repair Estimator** — authoritative line-item cost database; commercial license required. **Business decision pending** (see §7, R1).
- **BLS Producer Price Index** — free API, quarterly adjustment factors to keep Craftsman numbers current between editions.
- **Remodeling Magazine Cost vs. Value** — used citation-only for calibration, not as a data source.

Homewyse / HomeAdvisor / Angi are explicitly avoided — ToS prohibits commercial use and/or scraping.

---

## 2. Data schema

All new tables live in `atlas-db` (`packages/atlas-db/atlas_db/models.py`) with Alembic migrations under `apps/api/app/migrations/versions/`. All JSON columns are `JSONB` in Postgres; schemas below are application-layer contracts.

### `kitchen_briefs`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `project_id` | UUID | FK `projects.id` ON DELETE CASCADE |
| `status` | VARCHAR(16) | enum: `drafting`, `complete` |
| `extracted_fields` | JSONB | structured brief (see below) |
| `created_at` | TIMESTAMPTZ | default `now()` |
| `updated_at` | TIMESTAMPTZ | default `now()` |

Indexes: `(project_id)`, `(status)`.

`extracted_fields` shape:

```json
{
  "intent": "remodel" | "new",
  "footprint": { "length_in": 144, "width_in": 120, "shape": "rectangle" },
  "existing": { "load_bearing_walls": [...], "plumbing_stacks": [...], "windows": [...] } | null,
  "program": { "cook_frequency": "daily", "entertains": true, "accessibility_needs": [...] },
  "must_haves": ["island", "pantry"],
  "must_avoids": ["galley"],
  "style_preferences": { "aesthetic": ["farmhouse", "warm"], "color_direction": "neutral-warm" },
  "budget": { "low": 50000, "high": 85000, "currency": "USD" },
  "address": { "street": "...", "city": "...", "state": "CA", "postal_code": "..." } | null,
  "freeform_notes": "string"
}
```

Conversation history lives in a sibling table (below) so the brief row stays small and indexable.

### `kitchen_brief_messages`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `kitchen_brief_id` | UUID | FK `kitchen_briefs.id` ON DELETE CASCADE |
| `role` | VARCHAR(16) | enum: `user`, `assistant`, `system` |
| `content` | TEXT |  |
| `extracted_delta` | JSONB | the fields this turn contributed to `extracted_fields` |
| `sequence` | INTEGER | strict monotonic per brief |
| `created_at` | TIMESTAMPTZ | default `now()` |

Indexes: `(kitchen_brief_id, sequence)` unique; `(kitchen_brief_id)`.

### `jurisdictions`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `locator_hash` | VARCHAR(64) | SHA-256 of normalized `(state, city, postal_code)` |
| `state` | VARCHAR(2) |  |
| `city` | VARCHAR(128) |  |
| `postal_code` | VARCHAR(16) |  |
| `code_edition` | VARCHAR(32) | e.g. `IRC-2021`, `IRC-2024`, `CRC-2022` |
| `amendment_pack_version` | VARCHAR(32) | bumps when we rebuild the rule pack |
| `amendment_details` | JSONB | `[{ section, text_summary, citation_url, effective_date }]` |
| `cached_at` | TIMESTAMPTZ | |
| `expires_at` | TIMESTAMPTZ | default `cached_at + 90 days` |

Indexes: `(locator_hash)` unique (hit by lookup), `(state, postal_code)`, `(expires_at)` for eviction.

IRC 2021 is the baseline; amendment packs ship in this order: California (CRC + Title 24 + CALGreen), NYC, Chicago, Houston. Any other address falls back to IRC 2021 with a visible "general guidance — please verify locally" banner per Principle 1.3 (honesty over polish).

### `constraint_sets`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `kitchen_brief_id` | UUID | FK `kitchen_briefs.id` ON DELETE CASCADE |
| `jurisdiction_id` | UUID | FK `jurisdictions.id` ON DELETE RESTRICT |
| `constraints` | JSONB | array of constraint objects (below) |
| `version_stamp` | VARCHAR(64) | `{code_edition}@{amendment_pack_version}+nkba-{version}` |
| `created_at` | TIMESTAMPTZ | default `now()` |

Indexes: `(kitchen_brief_id)`, `(jurisdiction_id)`, `(version_stamp)`.

Constraint object shape:

```json
{
  "id": "min-work-aisle-42in",
  "kind": "clearance" | "adjacency" | "placement" | "dimension" | "sightline",
  "hardness": "hard" | "soft",
  "weight": 1.0,
  "category": "code" | "ergonomic" | "user",
  "source": {
    "authority": "IRC-2021 R303.5" | "NKBA-G17" | "brief.must_haves[0]",
    "citation_text": "…",
    "best_practice": false
  },
  "parameters": { "min_distance_in": 42, "between": ["island", "counter"] }
}
```

The `best_practice` flag distinguishes code-required from best-practice rules (e.g. NKBA G17's 150 CFM island hood vs IRC's 100 CFM minimum). UI surfaces the distinction so users can decide where to compromise.

### `layout_candidates`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `constraint_set_id` | UUID | FK `constraint_sets.id` ON DELETE CASCADE |
| `seed` | INTEGER | solver seed |
| `geometry` | JSONB | `StructuredSheet`-shaped (see §5) |
| `validation_result` | JSONB | `{ passed: bool, checks: [{name, category, passed, reason}] }` |
| `ranking_score` | DOUBLE PRECISION | null until ranked |
| `rank` | INTEGER | null unless in the top-3; 1-indexed |
| `status` | VARCHAR(16) | enum: `generated`, `validated`, `rejected`, `ranked` |
| `created_at` | TIMESTAMPTZ | default `now()` |

Indexes: `(constraint_set_id, status)`, `(constraint_set_id, rank)` partial `WHERE rank IS NOT NULL`.

The `geometry` JSON extends `StructuredSheet` with a **`materials`** field per wall / floor / cabinet / counter / appliance surface. This is the ControlNet render contract: every visible surface has a material ID the segmentation mask can resolve.

```json
{
  "sheet_kind": "kitchen_layout_v1",
  "footprint": { "length_in": 144, "width_in": 120, "origin_in": [0, 0] },
  "walls": [
    {
      "id": "w-north",
      "polyline": [[0,0],[144,0]],
      "height_in": 108,
      "surfaces": {
        "interior": { "material_id": "paint.interior.warm-white", "pbr_hints": {"roughness":0.8} },
        "exterior": { "material_id": "paint.exterior.cream" }
      }
    }
  ],
  "floor": { "material_id": "wood.oak.plank-natural" },
  "ceiling": { "material_id": "paint.ceiling.flat-white", "height_in": 108 },
  "cabinets": [
    {
      "id": "cab-base-1",
      "kind": "base" | "upper" | "tall" | "island",
      "bbox_in": [x0, y0, x1, y1, z0, z1],
      "surfaces": {
        "front": { "material_id": "cabinet.shaker.white" },
        "box":   { "material_id": "cabinet.interior.birch-ply" }
      }
    }
  ],
  "counters": [
    { "cabinet_id": "cab-base-1", "material_id": "stone.quartz.white-vein", "edge_profile": "eased", "thickness_in": 1.25 }
  ],
  "appliances": [
    {
      "id": "app-range-1",
      "kind": "range_30",
      "bbox_in": [...],
      "surfaces": { "front": { "material_id": "appliance.stainless-brushed" } }
    }
  ],
  "fixtures": [ /* sink, faucet, hood, lighting */ ],
  "openings": [ /* doors, windows, passthroughs */ ],
  "structural_notes": [ /* load-bearing walls, plumbing stacks preserved */ ]
}
```

Material IDs are namespaced strings pointing into a separate, versioned **material library** (checked into the repo under `packages/atlas-core/atlas_core/materials/`). The library is the single source of truth for PBR hints, LoRA token, texture swatch thumbnail, and human-readable name. Schema-enforced at application layer; every `material_id` must resolve in the active library version referenced by the candidate.

### `render_requests`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `layout_candidate_id` | UUID | FK `layout_candidates.id` ON DELETE CASCADE |
| `style` | VARCHAR(32) | enum: `modern`, `farmhouse`, `traditional`, `industrial`, `transitional` |
| `camera` | JSONB | `{ angle: "hero" \| "wide" \| "over-island" \| custom, azimuth_deg, elevation_deg, target: [x,y,z], fov_deg }` |
| `status` | VARCHAR(16) | enum: `queued`, `running`, `done`, `failed`, `retry` |
| `provider` | VARCHAR(32) | `replicate`, `fal`, `self-hosted` |
| `model` | VARCHAR(64) | `flux-schnell`, `sdxl-controlnet-depth`, etc |
| `cost_cents` | INTEGER | null until settled |
| `requested_by_user_id` | UUID | FK `users.id` ON DELETE RESTRICT |
| `created_at` | TIMESTAMPTZ |  |
| `completed_at` | TIMESTAMPTZ | nullable |

Indexes: `(layout_candidate_id, status)`, `(status, created_at)` for worker polling.

### `render_outputs`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `render_request_id` | UUID | FK `render_requests.id` ON DELETE CASCADE |
| `asset_url` | TEXT | MinIO/S3 URL |
| `depth_iou_score` | DOUBLE PRECISION | quality gate metric (render-depth vs scene-depth IoU) |
| `metadata` | JSONB | `{ seed, prompt, negative_prompt, control_inputs: [...], model_version }` |
| `created_at` | TIMESTAMPTZ |  |

Index: `(render_request_id)`.

The quality gate: `depth_iou_score < 0.82` triggers automatic re-roll up to 3 times before surfacing failure to the user (R6 mitigation).

### `cost_estimates`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `layout_candidate_id` | UUID | FK `layout_candidates.id` ON DELETE CASCADE |
| `line_items` | JSONB | array: `[{category, description, low_cents, high_cents, unit, quantity, source}]` |
| `total_range_low_cents` | BIGINT |  |
| `total_range_high_cents` | BIGINT |  |
| `methodology_notes` | TEXT | human-readable explainer shown to user |
| `region_used` | VARCHAR(128) | e.g. `San Francisco Bay Area, CA` |
| `data_sources` | JSONB | `[{source: "craftsman", version: "2025", accessed_at: "..."}, ...]` |
| `created_at` | TIMESTAMPTZ |  |

Index: `(layout_candidate_id)`.

### `contractor_packages`

| column | type | notes |
|---|---|---|
| `id` | UUID | PK |
| `layout_candidate_id` | UUID | FK `layout_candidates.id` ON DELETE CASCADE |
| `red_flag_questions` | JSONB | `[{question, why_it_matters, good_answer_looks_like}]` |
| `bid_template` | JSONB | structured template homeowner can hand to contractors |
| `typical_quote_low_cents` | BIGINT |  |
| `typical_quote_high_cents` | BIGINT |  |
| `created_at` | TIMESTAMPTZ |  |

Index: `(layout_candidate_id)`.

### Migration ordering

1. `project_type` + `lifecycle_state` columns on `projects` (extend existing table).
2. `jurisdictions` + `kitchen_briefs` + `kitchen_brief_messages`.
3. `constraint_sets`.
4. `layout_candidates`.
5. `render_requests` + `render_outputs`.
6. `cost_estimates` + `contractor_packages`.

---

## 3. API surface

All endpoints live under `apps/api/app/routes/kitchens.py`. Auth uses a new `owned_project_for_read(project_id) -> Project` dependency — analogous to the existing `owned_drawing_for_read`, checks that the authenticated user owns or is a member of the project. Pair it with `owned_project_for_write` for mutating endpoints. Both go into `apps/api/app/core/dependencies.py`.

### `POST /kitchens/brief`

Start or continue the intake conversation. Idempotent by `(project_id, sequence)`.

**Request:**
```json
{
  "project_id": "UUID",
  "user_message": "string",
  "sequence": 7  // optional; client-supplied ordering hint
}
```

**Response:**
```json
{
  "brief_id": "UUID",
  "assistant_message": "string",
  "extracted_fields_snapshot": { ... },   // full brief state after this turn
  "required_fields_missing": ["footprint.shape", "budget"],
  "brief_complete": false
}
```

### `POST /kitchens/{brief_id}/generate`

Triggers the generation pipeline. Async. Returns immediately; work happens in the worker (§5 integration).

**Request:** empty body.

**Response:**
```json
{ "job_id": "UUID", "status_url": "/kitchens/{brief_id}/generate/status" }
```

### `GET /kitchens/{brief_id}/generate/status`

**Response:**
```json
{
  "job_id": "UUID",
  "phase": "compiling_constraints" | "solving" | "validating" | "ranking" | "done" | "failed",
  "progress_percent": 0-100,
  "message": "string",
  "error_code": null | "string"
}
```

### `GET /kitchens/{brief_id}/candidates`

**Response:**
```json
{
  "brief_id": "UUID",
  "constraint_set_version": "IRC-2021@v3+nkba-2024",
  "candidates": [
    {
      "id": "UUID",
      "rank": 1,
      "ranking_score": 0.87,
      "tradeoff_summary": "Largest island, but loses the pantry.",
      "geometry_url": "/kitchens/{brief_id}/candidates/{id}/geometry",
      "thumbnail_url": "...",
      "cost_range": { "low_cents": 5800000, "high_cents": 8200000 }
    }
  ]
}
```

Returns up to 3 ranked candidates plus a `survivors_count` field for diagnostic transparency.

### `POST /kitchens/{brief_id}/refine`

**Request:**
```json
{
  "target_candidate_id": "UUID" | null,   // null = applies to whole brief
  "user_message": "Can we make the island bigger?"
}
```

**Response:**
```json
{
  "kind": "local_edit" | "regenerate",
  "new_candidate_ids": ["UUID"] | null,
  "job_id": "UUID" | null,                // set if regenerate
  "assistant_message": "string"
}
```

Refinement interpretation classifier decides local vs regenerate; local edits mutate the target candidate in place (new version row; old marked `superseded`). Regenerate kicks off the generation pipeline with the updated constraint set.

### `POST /kitchens/{brief_id}/renders`

**Request:**
```json
{
  "candidate_id": "UUID",
  "style": "farmhouse",
  "camera": { "angle": "hero" }
}
```

**Response:**
```json
{ "render_request_id": "UUID", "status_url": "/kitchens/{brief_id}/renders/{id}" }
```

### `GET /kitchens/{brief_id}/renders/{render_request_id}`

**Response:**
```json
{
  "id": "UUID",
  "status": "queued" | "running" | "done" | "failed",
  "provider": "replicate",
  "model": "flux-schnell",
  "output": {
    "asset_url": "...",
    "depth_iou_score": 0.91,
    "metadata": { ... }
  } | null,
  "error_code": null
}
```

### `GET /kitchens/{brief_id}/cost-estimate/{candidate_id}`

**Response:**
```json
{
  "candidate_id": "UUID",
  "total_range": { "low_cents": 5800000, "high_cents": 8200000 },
  "line_items": [
    { "category": "cabinets", "description": "...", "low_cents": ..., "high_cents": ..., "source": "craftsman-2025" }
  ],
  "methodology_notes": "...",
  "region_used": "San Francisco Bay Area, CA",
  "data_sources": [ ... ]
}
```

### `GET /kitchens/{brief_id}/contractor-package/{candidate_id}`

**Response:**
```json
{
  "candidate_id": "UUID",
  "red_flag_questions": [
    { "question": "...", "why_it_matters": "...", "good_answer_looks_like": "..." }
  ],
  "bid_template": { ... },
  "typical_quote_range": { "low_cents": ..., "high_cents": ... }
}
```

### Progress streaming

Reuse the existing `/ws` websocket (see `apps/api/app/routes/websocket.py`). Pipeline phases emit typed events (`kitchen.generate.phase`, `kitchen.render.progress`) on the project's channel — the client already has the plumbing from the extraction progress UI.

---

## 4. Frontend routes

New under `apps/web/app/(protected)/`:

- **`/`** — the signed-in homepage, is replaced by a chat composer surface. Unauthenticated users still see the marketing landing at `/` via the middleware gate; authenticated users hit this component instead (handled by the protected layout redirect, not the marketing page).
- **`/kitchens/new`** — redirect target when a user starts a kitchen project. Creates a `Project` with `project_type = kitchen_remodel` or `kitchen_new` and a draft `KitchenBrief`, then redirects to `/kitchens/[id]`.
- **`/kitchens/[id]`** — project workspace. Three-panel layout:
  - Left: `BriefSidebar` — real-time extracted fields.
  - Center: chat transcript during intake; candidate cards once generation completes.
  - Right: inspector panel (placeholder during intake, fills with selected candidate's summary once generated).
- **`/kitchens/[id]/candidates/[candidate_id]`** — detail view:
  - 2D plan on the left, 3D walkthrough (existing `Model3DCanvas`) on the right.
  - Tabs below: Costs / Code / Contractor.
  - `RenderModal` trigger button near the 3D panel.
  - `RefineInput` persistent at bottom.

### Component organization under `apps/web/components/kitchens/`

- `ChatComposer.tsx` — homepage input. Textarea + submit; routes to `POST /kitchens/brief` under the hood.
- `ProjectTypePills.tsx` — kitchen / bathroom / retail / office / addition pills. Only kitchen is clickable in V1; others render with a "Coming soon" tooltip and reduced opacity.
- `BriefSidebar.tsx` — renders the current `extracted_fields` snapshot as a grouped read-only form.
- `ChatTranscript.tsx` — styled message list for intake conversation (distinct from the `/drawings/{id}/ChatPanel` — different context, different styling).
- `CandidateCard.tsx` — thumbnail + rank badge + cost chip + tradeoff summary.
- `CandidateDetail.tsx` — the `/candidates/[id]` view's body.
- `Plan2D.tsx` — renders the 2D annotated plan (session 6 will own the internals; this session commits the placeholder).
- `CostBreakdown.tsx`, `CodeReport.tsx`, `ContractorPackage.tsx` — tab panels.
- `RenderModal.tsx` — style + angle picker; polls render status.
- `RefineInput.tsx` — persistent chat at bottom of detail view; posts to `/refine`.
- `RenderGallery.tsx` — thumbnails of generated renders for the candidate.

The existing `apps/web/components/viewer/Model3DCanvas.tsx` is reused unmodified; the new kitchen code passes its `Scene3D` JSON in directly.

### Marketing vs. app surface separation

`components/marketing/*` stays marketing-only (unauthenticated). `components/kitchens/*` is app-only (authenticated). No cross-imports except for the shared `Logo`, `DemoCTA`, and `lib/api.ts` modules.

---

## 5. Integration with existing code

### Reused unchanged

- `atlas_core.models.StructuredSheet` — the layout format for every generated candidate. See "extends below" for the one additive change.
- `atlas_core.reconstruct3d.reconstruct_sheet` — takes a `StructuredSheet` and produces the 3D `Scene3D` used by `Model3DCanvas`. Session 0 verifies it runs cleanly on a hand-built kitchen sheet.
- `apps/web/components/viewer/Model3DCanvas.tsx` — 3D walkthrough surface. No changes this session.
- Auth system (session + CSRF cookies), demo mode (`POST /auth/demo-login`, `scripts/seed_demo_account.py`), test harness safety (`tests/harness_safety.py`). No changes.
- Existing `fetchApi` / `lib/api.ts` proxy conventions. New client functions added alongside.

### Extended (additive, backwards-compatible)

- **`StructuredSheet.materials`** — new optional field on surface-bearing elements (walls, floor, ceiling, cabinets, counters, appliances). Older DXF-extracted sheets with no materials render in the existing untextured study-model palette; kitchen-generated sheets carry material IDs that the render pipeline consumes. Schema change is additive — no existing sheets or code break.
- **`reconstruct3d`** — propagates material IDs from sheet elements to `Scene3D` surfaces. When a material ID is absent, falls through to `STUDY_MODEL_PALETTE` as today.
- **`projects` table** — add `project_type VARCHAR(32)` (nullable; enum: `kitchen_remodel`, `kitchen_new`, `bathroom`, `retail_fitout`, `small_office`, `other`) and `lifecycle_state VARCHAR(32)` (nullable; enum: `briefing`, `generating`, `designing`, `priced`, `quoted`, `archived`). Nullable so existing rows migrate cleanly.

### Material library

New package directory: `packages/atlas-core/atlas_core/materials/`. Versioned (e.g. `library-v1.json`). Each material entry:

```json
{
  "id": "cabinet.shaker.white",
  "human_name": "Shaker cabinet, white paint",
  "pbr": { "albedo": "#F5F1EA", "roughness": 0.55, "normal_map": null },
  "render_hints": {
    "lora_token": "shaker-white-cab",
    "prompt_fragment": "white shaker-style cabinet with brushed nickel pulls"
  },
  "swatch_url": "..."
}
```

`atlas-core` validates IDs at load time; the API rejects candidate geometry with unresolved material IDs before persistence.

### What stays on the existing `/drawings/{id}` path

DXF extraction continues to exist and serves the "I already have drawings, analyze them" path for remodel users. Session 1 adds a link from the kitchen workspace to this path, but the two flows are otherwise independent. Nothing is deleted.

---

## 6. AI prompt design (skeletons)

Full prompts are developed per-session. These are load-bearing skeletons — the shape of the system message and the contract with callers.

### Intake (Opus)

```
You are Atlas's intake interviewer for kitchen projects.

Your job: conduct a warm, plain-language conversation with a
homeowner until you have a complete KitchenBrief. Ask one or two
questions per turn, never more. Never use architect jargon; use
"counter" not "countertop base cabinet," "stove" not "cooktop
assembly."

Required fields you must populate:
  - intent (remodel or new)
  - footprint (length, width, basic shape; remodels: existing plan or rough sketch)
  - must_haves, must_avoids, style_preferences
  - budget (even if rough)
  - address (city/state minimum — needed for code lookup)
  - program (cook frequency, entertaining, accessibility)

If the user asks for something physically impossible (e.g. a 12-foot
island in a 10-foot room), push back honestly before moving on.

When all required fields are filled, say so in plain language and
ask if they want Atlas to start designing.

Tone: advocate, not assistant. You are on the user's side.

Output format: natural language reply plus a JSON delta describing
which extracted_fields you learned from this turn.
```

### Constraint translation (Sonnet)

```
You are a constraint compiler for kitchen layouts.

Input: a KitchenBrief and a Jurisdiction record.
Output: a ConstraintSet JSON per the schema in v1-kitchen-architecture.md §2.

Rules:
  - Every constraint carries an authority citation.
  - Tag code-required vs best-practice correctly. NKBA numbers are
    best-practice unless the local code adopts them.
  - Produce hard constraints for anything load-bearing (code,
    physically impossible, must-haves). Produce soft constraints
    with weights for preferences and best-practice ergonomics.
  - Do not invent rules. If a rule you'd normally apply isn't
    supported by the inputs, omit it and note it in an "advisory"
    array so the UI can surface the gap honestly.

Output strict JSON only.
```

### Ranking (Opus)

```
You are Atlas's ranking architect.

Input: a KitchenBrief and an array of validated layout candidates.
Output: the top 3 candidates with tradeoff summaries.

For each top pick, give:
  - rank (1, 2, 3)
  - a one-sentence tradeoff summary in homeowner language
  - a two-sentence "why this one" note calibrated to the user's
    stated priorities

Rules:
  - Prioritize user must_haves, then ergonomic best-practice, then
    aesthetic alignment, then cost headroom.
  - If two candidates are very similar, keep only one unless they
    trade off meaningfully.
  - If fewer than 3 survivors exist, say so honestly rather than
    padding the list.

Be specific in tradeoffs: "larger island but loses pantry," not
"different layout."

Output strict JSON.
```

### Refinement interpretation (Sonnet)

```
You are Atlas's refinement interpreter.

Input:
  - current LayoutCandidate geometry
  - user's refinement message
  - the ConstraintSet the candidate was generated from

Decide:
  - "local_edit" if the change affects one or two objects and can
    be done without re-solving (e.g. move sink 12 inches, swap
    cabinet finish).
  - "regenerate" if the change shifts constraints (e.g. "add a
    pantry," "make the kitchen bigger") and the whole layout needs
    re-solving.

Output:
  - {kind, edit_delta} for local_edit (describe the mutation
    precisely enough that a deterministic transform can apply it)
  - {kind, new_or_changed_constraints[]} for regenerate (constraint
    objects to add or replace in the ConstraintSet)
  - {kind: "clarify", questions[]} if the request is ambiguous

Output strict JSON.
```

---

## 7. Testing strategy

### Unit tests

Per module. Every package under `packages/atlas-core/` and every route under `apps/api/app/routes/` has tests in the adjacent `tests/` directory. Python: pytest; TypeScript: not required at unit level (prefer integration).

### Integration tests

Full pipeline, end-to-end, hitting a real Postgres and Redis via the harness-safety layer. Covered paths:

1. Intake → brief_complete.
2. `/generate` → job completes → `/candidates` returns ≥3 survivors.
3. `/refine` → classifies correctly → applies delta or regenerates.
4. `/renders` → mock render provider → `render_output` row with IoU.

LLM calls are recorded-and-replayed (cassette-style) so CI doesn't burn API credits or drift. Re-record gates live in a separate `RECORD=1 pytest -m kitchen_llm` target.

### Acceptance benchmark suite

**20 canonical kitchen briefs** committed under `packages/atlas-core/atlas_core/benchmarks/kitchen/`. Mix of:

- Scopes: 7 light remodels, 8 full remodels, 5 new-construction.
- Jurisdictions: 5 × CA, 3 × NYC, 3 × Chicago, 3 × Houston, 6 × IRC-2021 fallback.
- Styles: each of modern/farmhouse/traditional/industrial/transitional at least 3×.
- Constraints: 3 with must-haves that force hard pivots; 2 with impossible requests to verify honest pushback.

Run on every merge to main:

```
poetry run kitchen-bench --suite all --record-metrics
```

Produces a JSON metrics file per run with plan-target fields:

- generation_success_rate
- validity_rate (candidates passing validation / total generated)
- ranking_stability (same brief + seed → same top-3)
- refinement_convergence (5 consecutive refinements without score degradation)

Fail the CI run if any metric crosses the target threshold.

### Manual quality review

**50 candidate layouts inspected per major change** (solver rework, constraint library expansion, validator changes, material library update). Review sheet in `docs/research/kitchen-qa-reviews/` with the plan-reviewer smell test: would a licensed code official approve this?

### Render quality gate

Every render that hits `render_outputs` is scored against the scene depth map. Threshold: IoU ≥ 0.82 ships to the user; below triggers automatic re-roll (up to 3× per request). Below 0.70 after 3 retries emits a `render_failed` error with a "try a different style or angle" hint — never surface a bad render.

Manual spot-check: 100 renders per material-library version, 2-of-3 independent evaluator pass rate required before library version is marked `production`.

---

## Risk register delta (additions to plan §6)

The plan registered 6 risks. Research surfaced 6 additional risks, numbered R1–R6 to stay distinct from plan §6.

- **R1 — Craftsman licensing fails.** Mitigation: cost data is pluggable behind a `CostBackend` interface; a fallback backend driven by published RSMeans digests + BLS PPI exists as an emergency alternative, even if less line-item-accurate.
- **R2 — CP-SAT solve-time blowup on >40 objects.** Mitigation: hierarchical zone decomposition — prep zone, cook zone, cleanup zone, storage zone — solved sequentially with interfaces fixed. Keeps each sub-solve under 20 objects.
- **R3 — Flux commercial license ambiguity.** Mitigation: the Session 7 benchmark is the forcing function. If Flux Schnell's license or terms drift, SDXL is the default. Flux Pro stays deferred.
- **R4 — Jurisdiction rule drift.** Mitigation: `amendment_pack_version` is version-stamped into every `ConstraintSet` and every `CostEstimate`. Rule packs rebuilt quarterly; out-of-date packs flagged in UI with a refresh CTA.
- **R5 — NKBA copyright on prose/illustrations.** Mitigation: we encode **numbers** (those are facts, not copyrightable) and write our own prose and illustrations. No copy-paste from NKBA materials.
- **R6 — ControlNet geometry warping.** Mitigation: depth-map IoU quality gate (see §7). Retry up to 3×. Human-review batches before new material-library versions ship.

---

## Answers to the plan's open questions

1. **Constraint programming library:** OR-Tools CP-SAT.
2. **AI rendering provider:** Benchmark Flux Schnell vs SDXL+ControlNet in Session 7; host on Replicate for V1 regardless; migrate to self-host at ~50K renders/month.
3. **Priority jurisdictions:** IRC 2021 baseline; amendment packs in order California → NYC → Chicago → Houston. Every other address falls back to IRC 2021 with a visible "please verify locally" banner.

---

## What Session 1 inherits from this commitment

- A schema every downstream session can code against.
- A defined API surface the frontend can stub.
- A material library contract the render pipeline will consume.
- A decision log: no further research churn required on solver, LLM choice, or render host.
- A testing harness blueprint to stand up alongside each subsystem.
