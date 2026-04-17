# M4 Phase 3 — IFC static probe

**Status:** diagnostic — does **not** validate the M4 DXF gap fixes.
**Date:** 2026-04-17.
**Scope:** static text analysis of the 3 Tier 3 buildingSMART IFC
files (`tier3/buildingsmart-pcert-building-{architecture,hvac,structural}.ifc`)
authored with SketchUp 2024 + BIM-Tools IFC Manager 5.3.3, schema
IFC4.

Atlas has no IFC reader yet (G-R4 is the DXF-side analogue and is
post-MVP). This probe inventories what the files contain so that
*when* an IFC reader arrives — or when a real DXF corpus lands —
we have a reference point for what the buildingSMART samples can
and can't exercise.

---

## What's honestly in these files

### Element inventory (raw STEP entity counts)

| Entity                         | arch | struct | hvac |
|--------------------------------|-----:|-------:|-----:|
| IFCWALL / IFCWALLTYPE          | 4/4  | 4/4    |  0/0 |
| IFCSPACE / IFCSPACETYPE        | 2/2  |   0    |   0  |
| IFCSLAB / IFCSLABTYPE          | 3/3  |   0    |   0  |
| IFCBEAM                        |   0  |   6    |   0  |
| IFCBUILDINGELEMENTPROXY        |   5  |   3    |   2  |
| IFCAIRTERMINAL / IFCDUCTSEGMENT|   0  |   0    | 2/1  |
| IFCDOOR                        | **0**|   0    |   0  |
| IFCWINDOW                      | **0**|   0    |   0  |
| IFCCOLUMN                      | **0**|   0    |   0  |
| IFCCURTAINWALL / IFCSTAIR      |   0  |   0    |   0  |
| IFCEXTRUDEDAREASOLID           |   2  |   —    |   —  |
| IFCTRIANGULATEDFACESET         |  12  |  17    |   5  |
| IFCPOLYLINE                    |   2  |   0    |   0  |

### What this corpus *does* cover

- **Type/instance pattern (IFCWALLTYPE ⇐ IFCRELDEFINESBYTYPE ⇐
  IFCWALL).** This is the IFC analogue of a DXF INSERT referencing
  a block definition (G-R3). An IFC reader would need the same
  "resolve type → use instance's local placement" logic that
  `dxf._entity_to_candidates` uses for INSERT.
- **Mixed geometry representations.** Walls in the architecture
  file use `IFCEXTRUDEDAREASOLID` over a profile (the clean case),
  while structural walls and everything in HVAC are delivered as
  `IFCTRIANGULATEDFACESET` meshes. An IFC reader can't assume a
  swept profile; it has to handle both.
- **IFCSPACE explicit rooms.** The architecture file carries 2
  named `IFCSPACE` instances ("living room", "entry hall") — the
  direct analogue of DXF `A-ROOM` polygons that G-O1 dedup was
  built to handle.
- **Spatial hierarchy.** `IFCRELCONTAINEDINSPATIALSTRUCTURE` +
  `IFCRELAGGREGATES` thread project → site → building → storey →
  element. DXF has no equivalent; an IFC reader has to either
  flatten this to sheet + source or extend the data model.

### What this corpus *doesn't* cover — and why that matters

- **No doors, windows, or columns.** The M4 Phase 1 fixes
  (G-R3 INSERT door/window/column, G-C1 window classification) have
  *zero analogue in this corpus*. If all we had were these files,
  we couldn't tell whether those fixes work or not.
- **No curved walls / splines.** G-R1 (SPLINE wall flattening) has
  no IFC analogue here — no `IFCSWEPTDISKSOLID`, no curved
  `IFCEXTRUDEDAREASOLID` profile, no `IFCBSPLINECURVE`. Curved
  walls simply don't appear.
- **No multi-vertex / L-shaped walls.** G-R5 (multi-segment
  polyline hosting) — the wall profiles here are trivial
  rectangles. No L-shaped exterior envelope, no wing-walls.
- **Trivial scale.** 4 walls × 3 files isn't a "professional
  drawing." A real Revit export of a single-family home easily
  yields 80+ walls, 30+ doors, 20+ windows, plus MEP. The
  buildingSMART PCERT is a reference file for IFC *schema
  validation*, not for complexity testing.
- **No DXF.** This is the inescapable one. M4 Phase 1 + 2 fix DXF
  extraction. Running anything through IFC doesn't exercise the
  code path that was changed.

### Gap-fix analogues, documented not validated

| M4 fix | IFC analogue                                          | Present in corpus? |
|--------|-------------------------------------------------------|:------------------:|
| G-R3   | IFCRELDEFINESBYTYPE → IFCDOOR/IFCWINDOW/IFCCOLUMN     | No (types exist, but only for walls/slabs) |
| G-C1   | IFCWINDOW instances                                   | No |
| G-R1   | Curved `IFCEXTRUDEDAREASOLID` profile / IFCBSPLINECURVE | No |
| G-O1   | IFCSPACE explicit + wall-bounded derivation           | Partial — 2 IFCSPACE exist, but no wall loop to derive against because walls are 3D meshes, not 2D footprints |
| G-R5   | Multi-vertex wall profile / chain of IFCWALL segments | No |

---

## What this probe proves

**That the IFC reader gap (G-R4) is real and concrete.** If the
corpus grows to include a Revit export of a commercial building,
an IFC reader is the *faster* path to structured data than trying
to round-trip through DXF. The type/instance pattern + geometry
representation variants are the real work; the file format itself
is just STEP.

**That the buildingSMART PCERT corpus, alone, is insufficient for
Phase 3 validation.** It stresses schema coverage, not
author-complexity. For real M4 validation we need drawings that
actually exercise doors, windows, columns, curves, and L-shaped
walls — which is exactly what the procurement punch list
(`m4-phase3-procurement.md`) enumerates.

## What this probe does *not* prove

**Anything about the M4 DXF extractor.** No DXF code path ran
against these files. The synthetic Tier 1 fixtures remain the only
test surface for G-R1/G-R3/G-R5/G-C1/G-O1 until real CAD samples
land.
