# M2 — Decision log

Canonical record of M2 architecture decisions. Each entry captures
*what* we decided, *when*, and *why* — including the research that
informed it. Reverse-chronological (newest first).

Format:

```
## D-NN — Short title
**Status:** open | decided | superseded
**Decided:** YYYY-MM-DD (or "—" if open)
**Informed by:** links to research notes / external sources

**Context.** What forced the decision?
**Decision.** What we picked.
**Rejected alternatives.** What we considered and why we didn't pick it.
**Consequences.** What this commits us to (good and bad).
```

---

## Open decisions waiting on research

These were flagged at the start of M2; the research notes in this
folder are explicitly scoped to close them.

| ID    | Question                                       | Blocked on                       |
|-------|------------------------------------------------|----------------------------------|
| D-06  | Scope of the generative-design track and its relationship to the analytical milestones | product input (no research note yet — this is a strategy/scope question, not an evidence question) |

D-01..D-05 are now closed — see "Decided" below.

---

## Open — strategy

### D-06 — Generative-design track alongside analytical milestones
**Status:** open (deferred — see "Decision" below)
**Decided:** —
**Informed by:** product owner direction; no external research yet (the open work here is product definition, not literature review)

**Context.** The original M0 framing positioned Atlas as analysis-first
("Architecture that checks itself") with a milestone plan of
ingest → structured drawings → coordination → Q&A → review → teams.
The product owner has since expanded the vision: Atlas should serve
the entire AEC workflow from concept-stage generation through to
construction-phase analysis — homeowner sketches, architect coordination,
contractor takeoffs, etc. Generative design becomes a peer track to
the analytical one, not a follow-on.

This forces three coupled decisions:
1. Sequencing — do the two tracks run in parallel, or does one ship
   end-to-end before the other starts?
2. Scope of the generative track — "generative design" in AEC covers
   at least 5 distinct products (auto floor-plan from brief,
   parametric form-finding, daylight/structural optimization,
   LLM-driven schematic options, site massing). Atlas needs to pick.
3. Shared infrastructure — how much of the existing M1 stack actually
   transfers (auth, queue, S3, design tokens, frontend lib: yes;
   the drawings/sheets/tiles data shape: probably not, since
   generative outputs are option trees rather than one-PDF-per-row).

**Decision.** **Deferred** until M2 ships end-to-end. Two reasons:
- M2 (structured drawings — understanding building elements as
  geometry) is foundational to *both* tracks. An extracted wall and
  a generated wall live in the same conceptual space; both need to
  be queryable, renderable, editable. Building M2 first keeps the
  shared foundation intact regardless of which generative product we
  eventually pick.
- The HANDOFF rule ("each milestone ships end-to-end before the
  next starts") exists for a reason — parallel tracks on a solo
  project tend to leave both at 80% and ship neither. Reaffirming it
  here is the conservative choice.

**Rejected alternatives.**
- *Start the generative branch in parallel now.* Would slow M2;
  scope still undefined; high risk of throwaway code. Reconsider
  after M2 if the generative product brief is concrete by then.
- *Drop the generative direction entirely.* Closes off a strategic
  option without basis. The vision can stay live in this doc even
  while the implementation waits.

**Consequences this has on still-open M2 decisions.**
- **D-05 (provenance) generalizes.** What I sketched as
  `extraction_runs` should probably be `element_sources` with a
  `source_kind` discriminator (`extraction` | `generation` |
  `manual_override`). Same shape, broader meaning. Cheap to design
  in now, expensive to retrofit.
- **D-01 (table layout) is unchanged but reinforced.** Polymorphic
  `elements` becomes more attractive — generated elements have the
  same kinds (room/wall/door/window) as extracted ones, just
  different provenance. Per-kind tables would force us to duplicate
  every table for "extracted" and "generated" or add a flag column,
  both ugly.
- **D-03 (extraction pipeline) splits.** The "extractor" abstraction
  becomes a "source" abstraction with at least two implementations
  (extractor, generator). Worker plumbing should be designed
  source-agnostic from the start.
- **Frontend.** When we get to the upload/landing redesign, the entry
  point should branch into "Analyze existing drawings" vs "Create
  new project" — but that's a Phase-3+ concern for M2's frontend
  slice and shouldn't gate the schema work.

**Open follow-ups (must close before unfreezing this decision).**
- Which specific generative product does Atlas ship first? (One
  paragraph: output, input, target user, MVP success criterion.)
- Does the existing brand line ("Architecture that checks itself")
  stay, or does the expanded scope want a new tagline?
- What does "homeowner sketch → analysis → architect coordination
  → contractor takeoff" look like as a single end-to-end workflow,
  or are these separate user journeys that share infra but not
  state?

---

## Decided

### D-05 — Provenance model
**Status:** decided
**Decided:** 2026-04-17
**Informed by:** [04](./04-confidence-and-provenance.md); user research session via Claude Chrome (2026-04-17)

**Context.** Atlas needs to surface where each element came from
(which extractor / generator / human override at what version) and
how confident we are in it. Provenance must support both extraction
*and* generation per [D-06](#d-06--generative-design-track-alongside-analytical-milestones).

**Decision.**
- A separate `element_sources` table records each "production run"
  — extraction, generation, or manual_override — with producer name,
  version, status lifecycle (queued/running/completed/failed), and
  free-form params/summary JSONB blobs.
- Every element rows FK to one source. Re-running an extractor
  inserts a *new* source + *new* elements; the old ones stay in
  place (queryable by source) so we can diff runs.
- `confidence` is a single nullable scalar in `[0, 1]` on each
  element; null means "not probabilistic" (manual / deterministic).
  Per-attribute confidence and alternative hypotheses are explicitly
  out of scope for M2 — revisit if/when an extractor produces them.

**Rejected alternatives.**
- *No source table — extractor stamp on each element directly.*
  Loses the run-level lifecycle (no "this run failed halfway"
  story) and complicates re-extraction UX.
- *Per-attribute confidence map.* Premature; nothing in the M2
  extractor pipeline produces it.

**Consequences.** Soft-delete on re-extraction is *not* automatic —
elements from older sources stay live unless caller filters by
"current source". The API will need a "active source per drawing"
concept eventually; for M2 we just expose source_id on every
element response and let the frontend pick the latest.

---

### D-04 — Build vs reuse for extraction stack
**Status:** decided
**Decided:** 2026-04-17
**Informed by:** [03](./03-tooling-survey.md); user research session via Claude Chrome (2026-04-17)

**Context.** AEC has a mature OSS ecosystem for the file-format
side; the ML side is thinner. Picking the right reuse boundary
shapes the worker-side dependency footprint and CI image size.

**Decision.** Reuse for file I/O and geometry; build for the
Atlas-specific glue:
- **DXF input:** `ezdxf` (mature, Python-native, MIT).
- **IFC input/output:** `ifcopenshell` (the reference impl; LGPL —
  call it from a subprocess or treat the LGPL boundary carefully).
- **Geometry ops:** `shapely` (2D ops, polygons, intersections),
  spatial indexing via `shapely.STRtree`. No PostGIS yet (see D-02).
- **OCR for room labels / sheet titles:** start with Tesseract via
  `pytesseract`. Revisit PaddleOCR / EasyOCR if rotated-small-text
  accuracy is bad on real sheets.
- **Floor-plan parsing models:** *defer*. M2 ships a deterministic
  pipeline (NCS layer parsing + geometric validators + OCR) before
  reaching for a CNN. Re-evaluate at M3 once we know what the gap
  is.
- **Extraction glue (NCS layer parser, validators, source
  orchestration):** built in-house under `worker.extractors.*`.

**Rejected alternatives.**
- *Bundle a CubiCasa5K-style model up front.* Adds ~hundreds of
  MB to the worker image, GPU dependency, and an opinion the
  research didn't yet justify.
- *Skip ezdxf/ifcopenshell, parse formats ourselves.* Wasteful;
  these formats are huge specs and the libraries are battle-tested.

**Consequences.** Worker image grows by ~the apt deps of poppler +
the `ezdxf`/`shapely`/`pytesseract`/`tesseract-ocr` packages. CI
build time goes up modestly; no GPU required.

---

### D-03 — Extraction pipeline approach
**Status:** decided
**Decided:** 2026-04-17
**Informed by:** [02](./02-extraction-approaches.md); user research session via Claude Chrome (2026-04-17)

**Context.** "Extract walls/doors/rooms from a sheet" is the M2
worker's job. The research surfaced three approach families
(rule-based on vector / rule-based on raster / deep learning); the
question was which to ship first.

**Decision.** Hybrid pipeline, deterministic-first:
1. **NCS layer parsing.** When the source is vector (DXF or
   layered PDF), the National CAD Standard layer naming convention
   (`<discipline>-<major>-<minor>-<modifier>`) is a strong signal.
   Walls live on `A-WALL-*`, doors on `A-DOOR`, etc. Parse the
   major/minor groups to classify entities cheaply.
2. **Geometric validators.** Confirm classification with cheap
   geometric checks: walls = parallel double-line patterns within
   a thickness tolerance; doors = arc + line pair (the swing);
   rooms = closed loops of walls.
3. **OCR for labels.** Tesseract over the rasterized sheet to
   pull room names/numbers; spatial-join the recognized text into
   the room polygon it sits inside.

A CNN-based parser (CubiCasa5K-style) is the explicit fallback
plan if the deterministic pipeline can't reach acceptable recall
on real-world sheets — but we ship the deterministic version
first because it's debuggable, doesn't need a GPU, and works on
the structured input we expect (most production AEC PDFs are
vector).

**Rejected alternatives.**
- *DL-only.* Premature; vector-side data is cheaper to exploit.
- *Vector-only.* Cuts off legacy scanned drawings entirely.

**Consequences.**
- The "source" abstraction needs to express "deterministic
  extractor on vector input" *and* "OCR on raster input" as siblings.
  Current `element_sources.producer_name` covers it.
- We need NCS layer fields on every element so a downstream user
  can ask "which entities did the layer parser pick up vs which
  ones are validator-confirmed only" — see D-01.

---

### D-02 — Geometry storage
**Status:** decided
**Decided:** 2026-04-17
**Informed by:** [01](./01-element-schema-standards.md), [02](./02-extraction-approaches.md); user research session via Claude Chrome (2026-04-17)

**Context.** Geometry can live as JSONB (no extension, simple
schema, no spatial queries) or PostGIS (`geometry(...)`, GiST
indexes, `ST_Intersects` etc.). M3 will want spatial queries for
clash detection.

**Decision.** **JSONB now, PostGIS in M3.** M2's queries are all
"give me elements on this sheet" or "give me elements of kind X"
— FK + secondary index do those without spatial machinery. The
JSONB shape mirrors atlas-core's Pydantic models exactly (Point,
Polyline, Polygon as nested objects), which is the cheapest
serialization.

Migration to PostGIS in M3 will be mechanical: add a
`geometry geometry(Geometry, 0)` column, backfill from JSONB via
`ST_GeomFromGeoJSON`, drop or keep JSONB as a debug surface.

**Rejected alternatives.**
- *PostGIS upfront.* Adds an extension to the Postgres image and
  a learning curve we don't yet need to climb. Cost without
  matching benefit in M2.
- *Custom binary format.* No.

**Consequences.** Bbox is stored separately as a JSONB blob with
`{minx, miny, maxx, maxy}` so the API can do coarse range queries
without parsing full polygons. Index plan deferred to M3.

---

### D-01 — Element table layout
**Status:** decided
**Decided:** 2026-04-17
**Informed by:** [01](./01-element-schema-standards.md); user research session via Claude Chrome (2026-04-17)

**Context.** Choice between one polymorphic `elements` table (kind
discriminator + JSONB attrs) vs per-kind tables.

**Decision.** **Polymorphic.** Single `elements` table, `kind`
column with CHECK constraint matching the `ElementKind` enum,
JSONB `attrs` for kind-specific fields, JSONB `geometry` for the
shape, JSONB `ifc_properties` for IFC property sets
(`Pset_WallCommon`, `Pset_DoorCommon`, etc.).

This matches both:
- atlas-core's discriminated-union Pydantic shape (`DrawingElement
  = Room | Wall | Door | Window | GenericElement`),
- the IFC entity model, where `IfcWall`/`IfcDoor`/etc. all derive
  from `IfcBuildingElement` and carry property sets as a uniform
  `IfcPropertySet` collection.

D-06 reinforces this — generated and extracted walls share the
same row shape, just with different `source_id`.

**Rejected alternatives.**
- *Per-kind tables.* Forces N-table joins for "all elements on
  sheet X" (the dominant query); makes adding element kinds a
  migration; doubles up under D-06 (would need extracted_walls +
  generated_walls or a flag column).
- *Single-table inheritance with all columns physically present.*
  Hideous; explicit JSONB is honest about the polymorphism.

**Consequences.**
- IFC-typed columns (`ifc_type`, `ifc_properties` JSONB) are
  required from day one — late-add would force an awkward
  migration and a re-extraction pass.
- NCS layer fields (`ncs_layer`, `ncs_major_group`,
  `ncs_minor_group`) are first-class columns rather than living
  inside `attrs` so they can be indexed for "find all
  architectural walls" queries.
- Self-FK `host_element_id` lets doors/windows reference their
  host wall — supports D-03's geometric validators (door swing
  must intersect a wall).
- Adding new kinds is data-only (extend the enum + CHECK
  constraint, no DDL beyond that).
