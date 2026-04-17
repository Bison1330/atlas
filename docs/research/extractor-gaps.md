# Extractor + connectivity gaps — known limitations

Catalogued from a code review of `worker/extractors/dxf.py`,
`atlas_core/connectivity.py`, and the M2 / M3-Phase-2 orchestrator
on commit `0af502c` (M3 Phase 2 + infra wire-up).

**Why this exists.** Until real-world CAD samples (Tier 2 corpus
files) are dropped in and run through `scripts/eval_extraction.py`,
the eval runner only validates synthetic fixtures we built
ourselves. That covers correctness on the cases we anticipated,
not coverage on the cases we didn't. This doc enumerates the
*anticipated* gaps so prioritization isn't ambient. Each gap has:

- **Symptom** — what would happen on a drawing that exercises it.
- **Where** — the file/function that needs work.
- **Severity** — *blocker* (will silently mis-extract real data),
  *limitation* (extractor produces nothing for this input but
  doesn't lie about it), or *cosmetic*.
- **Fix shape** — the rough plan.

---

## Reader: entity coverage

### G-R1 — SPLINE walls produce nothing
**Severity:** limitation
**Symptom:** Curved or arc-blended walls (common in residential plans
with rounded interior corners, in commercial lobbies, in landscape /
site plans) drawn as DXF `SPLINE` entities are silently ignored —
the reader never even classifies them. They don't appear in the
candidate list at all.
**Where:** `dxf._entity_to_candidates` (apps/worker/worker/extractors/dxf.py)
— only checks for `LINE` / `LWPOLYLINE` on wall layers.
**Fix shape:** Add a SPLINE → polyline approximation pass (ezdxf has
`spline.flattening()` for this). Decision required: how many
segments per spline (controls fidelity vs element count).

### G-R2 — POLYLINE (legacy 2D) treated differently than LWPOLYLINE
**Severity:** limitation
**Symptom:** Older DXFs (pre-R14, or anything authored in legacy
software) use `POLYLINE` entities, not `LWPOLYLINE`. Reader handles
LWPOLYLINE only; legacy POLYLINEs land in `skipped_entity_types`.
**Where:** Same.
**Fix shape:** Add a POLYLINE branch that calls `entity.points()`
(ezdxf provides a unified iterator) and feeds the same geometry
shape downstream.

### G-R3 — INSERT (block reference) entities ignored
**Severity:** blocker for many real plans
**Symptom:** Doors and windows in production CAD are almost always
*block references* (INSERT entities pointing at a block definition
that contains the actual line/arc geometry). Our reader never
follows INSERT — so a Revit-exported DXF with all doors as inserted
"M_Door-Single" blocks produces zero door candidates.
**Where:** Same.
**Fix shape:** When an INSERT is on a known layer, either (a) flatten
its block contents and re-classify each child entity, or (b) treat
the INSERT itself as the element, using its insertion point + scale
as the implied geometry. (b) is much cheaper and matches how the
schedule data is usually attached.

### G-R4 — Nested layouts / xrefs not traversed
**Severity:** limitation
**Symptom:** Real plan sets are typically organized as a master DWG
with xrefs (external references) for each discipline / floor.
ezdxf's `doc.layouts` covers paperspace layouts within the file;
xref'd entities live in *other* files we don't open.
**Where:** `dxf._iter_all_entities`.
**Fix shape:** Out of scope for M2 / M3 Phase 2. Document as a Phase
4+ requirement; add an optional `--resolve-xrefs` mode that opens
referenced files relative to the source DXF's directory.

### G-R5 — Multi-segment LWPOLYLINE walls become one segment in hosting
**Severity:** ~~silent — but may produce wrong host attribution~~ — **resolved on `m4/real-cad-capability` (Phase 2).**
**Symptom:** A wall drawn as a single LWPOLYLINE with multiple
vertices (e.g. an L-shaped wall) is converted to a polyline
geometry with all the vertices, but the hosting algorithm in
`worker.jobs.extract._wall_segment` collapses it to *just the first
and last point* before passing to `host_walls_for_doors`. So a
door near the elbow of an L-shaped wall would either fail to host
or host on the wrong wall.
**Where:** `apps/worker/worker/jobs/extract.py:_wall_segment`.
**Fix shape:** ~~Either expand the polyline into N individual segments
before hosting (and remember the parent wall id for each), or
extend `host_walls_for_doors` to accept multi-segment chains
directly.~~ Implemented the first option: `_wall_segments` returns
consecutive-vertex pairs and the orchestrator keeps a parallel
`segment_parent` list so hosting resolves back to the original
Element row.

---

## Reader: classification

### G-C1 — Window detection produces nothing
**Severity:** blocker for any plan with windows (i.e. all of them)
**Symptom:** `MAJOR_GROUP_TO_KIND` maps `WIND` and `GLAZ` to
`ElementKind.WINDOW`, but `_entity_to_candidates` has no branch for
the WINDOW kind. So even a perfectly-NCS-tagged window entity
falls through the kind-specific switch and produces zero candidates.
**Where:** `dxf._entity_to_candidates`.
**Fix shape:** Add a WINDOW branch, probably keying on LWPOLYLINE
(some authors use lines for sills + jambs) or INSERT (block-based
windows — the dominant Revit/Archicad pattern, see G-R3).

### G-C2 — Wall thickness only captured from closed LWPOLYLINEs
**Severity:** limitation; affects M3 takeoffs (wall area) and any
future BIM export.
**Symptom:** Walls drawn as a single `LINE` (the dominant pattern
in our synthetic fixtures and in many CAD authoring environments
where centerlines are the source of truth) carry no thickness.
Walls drawn as a closed LWPOLYLINE (fewer authors do this) get
thickness from the geometry.
**Where:** `dxf._entity_to_candidates` wall branch.
**Fix shape:** Two avenues — (a) look for parallel-line pairs near
each centerline LINE (use the existing
`worker.extractors.geometry.lines_parallel`) to infer thickness
from the gap; (b) hard-code default thicknesses by NCS minor group
(EXTR ≈ 8" / 200mm, INTR ≈ 4" / 100mm) and flag as default-derived.

### G-C3 — IFC type defaults are approximations
**Severity:** cosmetic, with a downstream-correctness wrinkle.
**Symptom:** Every wall gets `ifc_type="IfcWallStandardCase"`. Real
walls span IfcWall, IfcWallStandardCase, IfcCurtainWall, IfcPlate,
etc. Our default is fine for stud-frame interior walls but wrong
for curtain walls (typical commercial exterior glazing system).
**Where:** `dxf._IFC_DEFAULTS`.
**Fix shape:** Punt until we have IFC export round-tripping; record
the default as a known-coarse approximation in the IFC reader work.

### G-C4 — Layer regex is permissive about trailing junk
**Severity:** silent; produces ElementKind.OTHER on garbage
**Symptom:** `ncs.parse_layer` accepts up to 4 alphanumeric chars
per group, but doesn't reject layer strings with too many groups
(e.g. `A-WALL-EXTR-FULL-N-EXTRA-EXTRA`). Anything past the 5th
field is silently dropped.
**Where:** `atlas_core` (NCS parser was moved here).
**Fix shape:** Cosmetic; add a strict mode that rejects extra
fields. Not worth doing until we see a real-world layer that this
mis-classifies.

---

## Connectivity

### G-K1 — Wall splitting doesn't handle collinear overlap
**Severity:** silent; produces extra "rooms" or misses rooms when
two walls draw the same edge
**Symptom:** When two LINE entities cover the same edge (a common
authoring artifact: drawing a wall over an existing one), the
intersection-finding code returns an empty list (parallel ⇒ no
finite intersection), and both edges land in the planar graph as
duplicate half-edges. The face walker then misbehaves.
**Where:** `connectivity._segment_intersections` returns `[]` for
parallel/collinear segments by design.
**Fix shape:** Detect collinear overlap during preprocessing; collapse
overlapping segments to one. ~30 lines of geometry; fits inside the
existing `split_walls_at_intersections`.

### G-K2 — Single connected component assumed for face walking
**Severity:** limitation; not silent (faces are still found per
component) but doesn't handle interior cutouts
**Symptom:** A room *inside* another room (a vestibule, an interior
courtyard) shows up as two separate CCW faces, but they're actually
nested — the outer face's "interior" excludes the inner face. We'd
report both as rooms with no nesting relationship.
**Where:** `connectivity.derive_rooms_from_walls`.
**Fix shape:** Post-process: for each pair of derived rooms, check
if one's bbox fully contains the other AND its boundary lies inside
the outer's polygon. Mark as `attrs.contains` / `attrs.contained_by`.

### G-K3 — Door hosting picks one wall even on the boundary between two
**Severity:** edge case (real plans rarely overlap walls exactly)
**Symptom:** If two walls happen to coincide (same LINE entity
drawn twice on different layers), the host check picks the
*first-listed* of the two by index, not necessarily the
right one (e.g. picks A-WALL-INTR when A-WALL-EXTR is what the door
visually belongs to).
**Where:** `connectivity.host_walls_for_doors` uses `<` not `<=`,
which makes ties go to the first match.
**Fix shape:** Add a tie-breaking rule (e.g. prefer the wall whose
NCS major matches the door's NCS minor for door-in-wall sets, prefer
EXTR over INTR for exterior door layers, etc.). Needs real input to
calibrate.

---

## Orchestrator

### G-O1 — Hosting + room derivation ignore explicit A-ROOM polygons
**Severity:** ~~correctness; produces *duplicate* rooms~~ — **resolved on `m4/real-cad-capability` (Phase 2).**
**Symptom:** A drawing with both well-drawn wall loops AND
explicit room polygons ends up with one Element row per source —
the explicit one has the author's name/number, the derived one has
geometry-from-walls but no name. The takeoff endpoint then
double-counts the area.
**Where:** `apps/worker/worker/jobs/extract.py:_run_connectivity_analysis`.
**Fix shape:** ~~Before inserting a derived room, check whether an
explicit A-ROOM element covers the same bbox + polygon (within
tolerance); if so, *attach* the derivation metadata to the
explicit element (set `attrs.derivation_confirmed = True`) instead
of inserting a duplicate.~~ Implemented: predicate lives in
`atlas_core.connectivity.dedup_derived_against_explicit` (bbox IoU
≥ 0.9 AND |Δarea| / max_area ≤ 0.1). On match, the explicit row
gets `attrs.derivation_confirmed = True` + `attrs.derived_area`
and the derived insert is skipped. Source summary gains a
`confirmed_explicit_rooms` counter.

### G-O2 — Re-extraction doesn't garbage-collect old derived rooms
**Severity:** correctness
**Symptom:** Re-running extraction creates a new ElementSource and
its own derived rooms — but the previous source's derived rooms
are still in the elements table (the takeoffs API filters by
source_id, but a UI showing "all rooms ever derived" would see
duplicates from prior runs).
**Where:** Currently a *feature* — runs are immutable, see
decisions.md D-05. But the implication for any future "show me all
rooms across runs" view is worth flagging.
**Fix shape:** None today; document as a consequence of D-05.

---

## Test coverage gaps (separate from product gaps)

### G-T1 — No test fixture exercises G-R3 (INSERT-based blocks)
The whole "real Revit/Archicad export" pattern (everything is
inside a block) has zero coverage. Will need either a synthetic
fixture that uses `ezdxf.add_blockref()` or a real Tier 2 file.

### G-T2 — No test fixture exercises G-K2 (nested rooms)
A donut-shaped plan (room with an interior courtyard) is missing
from the synthetic suite.

### G-T3 — No test fixture exercises G-K1 (collinear duplicate walls)
Trivial to add — duplicate one of the existing walls in
`build_one_room_floor` and assert it's collapsed.

---

## Prioritization (suggested)

For getting Atlas to "actually works on a real CAD export":

1. ~~**G-R3** (INSERT block flattening)~~ — **resolved on
   `m4/real-cad-capability`** via option (b): INSERT entities on
   door / window / column layers become point-elements using their
   insertion point as implied geometry. Fixture:
   `tier1/insert-elements-floor.manifest.yaml`.
2. ~~**G-C1** (window classification)~~ — **resolved on
   `m4/real-cad-capability`**: WINDOW branch added for LWPOLYLINE
   (open and closed) plus the INSERT path shared with G-R3.
   Fixtures: `tier1/polyline-window-floor.manifest.yaml` and
   `tier1/insert-elements-floor.manifest.yaml`.
3. ~~**G-R1** (SPLINE walls)~~ — **resolved on
   `m4/real-cad-capability`**: SPLINE on a wall layer is flattened
   via ezdxf's `flattening(distance=0.01)` into polyline geometry.
   Fixture: `tier1/spline-wall-floor.manifest.yaml`.
4. ~~**G-O1** (explicit + derived room dedup)~~ — **resolved on
   `m4/real-cad-capability`** (Phase 2). The orchestrator now
   computes bbox-IoU + area-fraction against explicit A-ROOM
   polygons and annotates the explicit element with
   `attrs.derivation_confirmed = True` / `attrs.derived_area`
   instead of inserting a duplicate. Predicate lives in
   `atlas_core.connectivity.dedup_derived_against_explicit`.
   Fixture: `tier1/explicit-and-derived-room-floor.manifest.yaml`.
5. ~~**G-R5** (multi-segment polyline hosting)~~ — **resolved on
   `m4/real-cad-capability`** (Phase 2). `_wall_segment` replaced
   with `_wall_segments` which expands each wall's polyline into
   consecutive-vertex segments; the orchestrator keeps a parallel
   parent-element map so `door.host_element_id` still resolves to
   the original wall row. Fixture:
   `tier1/l-shaped-wall-floor.manifest.yaml`.

Everything else is post-MVP and can be calibrated against real
inputs once they exist.
