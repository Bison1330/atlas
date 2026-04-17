# M4 Phase 3 — procurement punch list

**Why this exists.** Phase 3 is *real-drawing validation* of the
M4 gap fixes (G-R1, G-R3, G-C1, G-O1, G-R5). The current corpus
cannot do that job:

- Tier 1 (8 synthetic DXFs) validates what we *designed for*, not
  what real authoring tools produce.
- Tier 2 (target: Revit + Archicad exports) is **empty on disk** —
  license-gated, not fetchable from CLI.
- Tier 3 (3 buildingSMART IFC files) doesn't exercise DXF code at
  all, and even for IFC stresses schema coverage rather than
  author-complexity. See `m4-phase3-ifc-probe.md`.

Until the files listed below are on disk under
`tests/fixtures/corpus/tier2/`, Phase 3 is **blocked on
procurement, not on engineering.**

---

## Minimum viable Phase 3 corpus

Three files cover 90% of what M4 claims to fix. If only one of
these lands, the Revit export is the highest-signal pick.

### 1. `tier2/revit-rac-advanced-floor-1.dxf` — **required**

| Field | Value |
|---|---|
| Source | Autodesk Revit installer sample `rac_advanced_sample_project.rvt` (the Revit Architecture sample house), **exported to DXF** at "Floor Plan: Level 1" |
| How to fetch | Install a Revit trial → Home → Sample Files → `rac_advanced_sample_project.rvt` → File → Export → CAD Formats → DXF → scope: current view |
| License | Autodesk sample data EULA — **not redistributable**, do not commit |
| Size estimate | 2–5 MB |
| Stresses | G-R3 (every door, window, column in Revit exports as INSERT block references), G-C1 (window INSERTs on A-WIND-GLAZ), G-O1 (Revit emits both A-ROOM polygons *and* wall loops), G-R5 (curved and L-shaped interior walls on Level 1) |
| Why this one | Revit is the dominant authoring tool in North American commercial practice. If Atlas breaks on this, it breaks on the most common real input. |

### 2. `tier2/archicad-hillside-house.dxf` — **required**

| Field | Value |
|---|---|
| Source | Graphisoft Archicad installer sample "Hillside House" (~2,400 sf residential), exported to DXF |
| How to fetch | Install Archicad → Open Sample → Hillside House → File → Save As → AutoCAD DXF (choose "current view" + "model space") |
| License | Graphisoft Archicad EULA — not redistributable |
| Size estimate | 1–3 MB |
| Stresses | Archicad's slightly different NCS conventions vs. Revit (exercises `ncs.parse_layer` robustness), curved residential walls (G-R1), INSERT-based door/window blocks using Archicad's naming (G-R3) |
| Why this one | Residential patterns differ from Revit commercial patterns; a second tool's conventions catch parser assumptions. |

### 3. `tier2/permit-seattle-sdci-NNNNNN.pdf` — **recommended**

| Field | Value |
|---|---|
| Source | Any publicly-filed Seattle SDCI permit application (architectural sheet) |
| How to fetch | https://cosaccela.seattle.gov/Portal/welcome.aspx → search permits → pick one with an architectural floor-plan attachment |
| License | Public record — redact any owner/address info before public distribution |
| Size estimate | 5–20 MB |
| Stresses | Real PDF rasterization quality (M1 tile pipeline), mixed-quality line work, scanned vs. vector-native content — *not* the M4 DXF fixes directly, but exercises the full end-to-end upload → extraction flow on a non-synthetic source |
| Why this one | The permit world is where Atlas will actually operate; any detail that breaks in production is here first. |

---

## Reach goals

Not blocking Phase 3 sign-off, but valuable when available:

| File | Stresses | Why later |
|------|----------|-----------|
| `tier2/revit-snowdon-towers-L5.dxf` | High-rise, curtain-wall heavy | Curtain walls need IfcCurtainWall mapping (G-C3); out of M4 scope |
| `tier2/revit-technical-school-L1.dxf` | Educational floor plan, heavy MEP | MEP layers (P-, M-, E-) need NCS rules Atlas doesn't have |
| `tier3/autocad-ncs-sample.dxf` | NCS compliance validation in isolation | Distinct from authoring-tool edge cases |
| `tier3/legacy-acad-2000.dxf` | Pre-R14 POLYLINE (G-R2) | G-R2 is limitation-severity, not blocker |

---

## Acceptance criteria for Phase 3 sign-off

Once the **required** files above are dropped in:

1. `scripts/eval_extraction.py tests/fixtures/corpus/tier2/revit-rac-advanced-floor-1.manifest.yaml` runs without skipping. Manifest expects:
   - Non-zero counts in *all five* kinds (wall, door, window, column, room)
   - At least one INSERT-sourced door (`attrs.source_entity == "INSERT"`)
   - `connectivity.confirmed_explicit_rooms > 0` (proves G-O1 fired on a real drawing)
   - At least one wall with more than 2 vertices (proves G-R5 fired)

2. Same for `archicad-hillside-house.manifest.yaml`.

3. Takeoffs API on these two fixtures returns a report with
   `total_area_units` within ~10% of the ground-truth floor area
   (pulled from the source file's schedule or measured manually).

4. No entity type lands in `skipped_entity_types` without a
   documented reason in `extractor-gaps.md`.

Until (1)–(4) hold, M4 is "works on synthetic; real-drawing
coverage unknown" — which is honest, but not yet "done".

---

## What not to do

- **Don't synthesize "realistic" fixtures.** We already know what
  our fixtures prove. Dressing one up to look Revit-ish (block
  names like `M_Door-Single`, paperspace layouts) doesn't expand
  the test surface — it just re-tests what Phase 1 fixtures
  already cover.
- **Don't `git add -f` the Tier 2 files once they land.** The
  `.gitignore` exists to keep license-encumbered content out of
  public git history. Keep them local.
- **Don't gate CI on Tier 2.** A fresh clone should still pass CI
  with the Tier 1 synthetic suite. The eval harness already
  `SKIP`s missing fixtures by design.
