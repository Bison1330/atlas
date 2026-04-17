# 03 — OSS tooling survey

**Status:** stub
**Owner:** —
**Last updated:** 2026-04-17

---

## Question

Which OSS components in the AEC / geometry / CV space are mature
enough to use as building blocks for M2 — and where are we forced to
build from scratch?

### Sub-questions

- [ ] **PDF vector parsing.** `pypdf`, `pdfplumber`, `pdfminer.six`,
      `pymupdf` — what does each give us for raw drawing primitives
      (lines, curves, text with positions)? License compatibility?
- [ ] **CAD format readers.** `ezdxf` for DXF; `libredwg` /
      `pylibredwg` for DWG; `ifcopenshell` for IFC. State of the
      art, license, ergonomic level.
- [ ] **Geometry libraries.** `shapely` (2D ops), `pyproj` (CRS),
      `triangle`/`mapbox-earcut` (polygon triangulation),
      `rtree`/`shapely.STRtree` (spatial index). Which combination
      is the standard stack?
- [ ] **Floor-plan parsing models.** CubiCasa5K (weights + license),
      Raster-to-Vector implementations on GitHub, any newer
      transformer-based variants? Are there permissive-license
      pre-trained weights we can ship?
- [ ] **Annotation / labeling tools.** If we end up needing to
      generate training data, what's the AEC-aware labeling tool of
      choice? (Label Studio, CVAT, custom?)
- [ ] **Coordination + clash-detection libraries.** Anything we'd
      reuse in M3 that influences how M2 stores geometry?

## Why this matters

Closes **D-04** (build vs reuse). Saves effort if there's mature
prior art; flags risks early if a critical capability has no good
OSS option (forcing us to either build it or pick a commercial
dependency).

## Sources

| # | Source | Type | Notes |
|---|--------|------|-------|
|   |        |      |       |

## Findings

### PDF vector parsers

- …

### CAD readers

- …

### Geometry libraries

- …

### Floor-plan parsing models

- …

### Labeling tools

- …

## Implications for Atlas

- …

## Open follow-ups

- …

## Decision log entries closed by this note

- [ ] D-04 — Build vs reuse for extraction stack
