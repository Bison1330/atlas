# 01 — Element schema standards

**Status:** stub
**Owner:** —
**Last updated:** 2026-04-17

---

## Question

What schema(s) does the AEC industry already use to represent rooms,
walls, doors, and windows extracted from drawings — and how closely
should Atlas's storage shape mirror them?

### Sub-questions

- [ ] What does **IFC** (Industry Foundation Classes — buildingSMART)
      define for `IfcSpace` (rooms), `IfcWall`/`IfcWallStandardCase`,
      `IfcDoor`, `IfcWindow`? Specifically: which attributes are
      required, which are optional, what's the geometry representation?
- [ ] **COBie** (Construction Operations Building Information Exchange) —
      what does it require for handover? Does it overlap usefully
      with what we'd extract?
- [ ] **DXF entities** — when starting from CAD natives, what's the
      typical mapping (ENTITY → architectural element)? Is there a
      conventional layer-naming standard (e.g. AIA CAD Layer Guidelines)?
- [ ] What about **CityGML** / **LandXML** — relevant or out of scope?
- [ ] How do production tools (Revit, ArchiCAD, Bentley) structure
      "I extracted these elements from a 2D drawing" outputs?
- [ ] Are there **content-addressable conventions** for element
      identity across re-extractions? (How does e.g. Speckle or
      Solibri stay stable across runs?)

## Why this matters

Closes **D-01** (polymorphic vs per-kind elements table) and feeds
into **D-02** (geometry storage). If the industry has converged on a
shape — even loosely — mirroring it costs us nothing today and saves
a painful migration when we want to import/export IFC in M5+.

## Sources

| # | Source | Type | Notes |
|---|--------|------|-------|
|   |        |      |       |

## Findings

### IFC entities for rooms / walls / doors / windows

- **Finding:** …

### COBie

- …

### DXF + AIA layer guidelines

- …

### Production tools

- …

## Implications for Atlas

- …

## Open follow-ups

- …

## Decision log entries closed by this note

- [ ] D-01 — Element table layout
- [ ] D-02 — Geometry storage (partial: schema shape, not type)
