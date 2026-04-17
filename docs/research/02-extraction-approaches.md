# 02 — Extraction approaches

**Status:** stub
**Owner:** —
**Last updated:** 2026-04-17

---

## Question

What's the state of the art for extracting architectural elements
(rooms, walls, doors, windows) from a sheet — and which approach
makes sense as Atlas's first extractor?

### Sub-questions

- [ ] **Vector vs raster source.** Most production AEC PDFs from
      Revit/AutoCAD are vector. How much can we get just by parsing
      the PDF content stream (lines, polylines, text) before
      reaching for CV? What proportion of "real" PDFs in the wild
      are pure raster scans?
- [ ] **Rule-based / heuristic extractors.** Wall detection from
      double-line patterns, door swings from arc + line pairs, room
      polygons from closed-loop wall enclosures. What's the
      precision/recall ceiling on these for clean CAD output?
- [ ] **Deep-learning approaches.** Floor-plan parsing networks
      (e.g. CubiCasa5K, R2V, FloorNet, Raster-to-Vector). What are
      the public benchmarks, dataset sizes, and weights availability?
- [ ] **Hybrid.** Recent papers / commercial tools that combine
      vector parsing with a CNN — what's the typical pipeline
      structure (e.g. CV proposes regions, vector parser confirms)?
- [ ] **Symbol detection** (doors, windows, fixtures). Template
      matching vs object-detection nets — what's currently winning?
- [ ] **OCR for sheet titles + room labels.** Tesseract still the
      default? PaddleOCR / EasyOCR alternatives? What works on the
      tiny rotated text in title blocks?

## Why this matters

Closes **D-03** (extraction pipeline shape) and informs **D-04**
(reuse vs build). The choice of extraction approach determines:
- whether Atlas needs a GPU in the worker (DL inference) or just
  more CPU (rule-based),
- what training data we need to gather (or not),
- which OSS components are candidates (atlas-extractor wrapping
  CubiCasa5K weights vs from-scratch shapely heuristics).

It also constrains the schema: a DL pipeline produces probabilistic
outputs that benefit from per-element confidence and alternative
hypotheses; a deterministic vector parser doesn't need that
machinery.

## Sources

| # | Source | Type | Notes |
|---|--------|------|-------|
|   |        |      |       |

## Findings

### Vector PDF extraction

- …

### Rule-based on raster

- …

### Deep-learning floor-plan parsing

- …

### Symbol detection

- …

### OCR

- …

## Implications for Atlas

- …

## Open follow-ups

- …

## Decision log entries closed by this note

- [ ] D-03 — Extraction pipeline approach
