# 04 — Confidence + provenance

**Status:** stub
**Owner:** —
**Last updated:** 2026-04-17

---

## Question

How do AI-assisted AEC tools surface uncertainty and provenance for
extracted elements — and what minimum schema does Atlas need to
match the convention?

### Sub-questions

- [ ] **Confidence representation.** Single scalar 0..1, calibrated
      probability, or something richer (per-attribute confidence,
      alternative hypotheses)? What do production tools (Bluebeam
      Revu, Procore, Autodesk Construction IQ, Togal.AI, Swapp)
      actually persist?
- [ ] **Extractor versioning.** How do tools track which extractor
      version produced which output? Per-element extractor stamp,
      per-run, both?
- [ ] **Reproducibility.** When a user re-extracts after a model
      update, do tools delete + re-insert, version the elements, or
      diff the runs? What's the UX expectation?
- [ ] **User overrides.** When a human corrects an extraction, how
      is that captured — as a new element, an annotation on the
      original, or a versioned record? Does the next extraction
      respect the override?
- [ ] **Audit trail.** What do AEC compliance regimes require for
      AI-assisted outputs? (E.g. AIA's positions on AI in design
      docs, any liability conventions.)

## Why this matters

Closes **D-05** (provenance model). Determines:
- the columns on `element_sources` and `elements` (do we need
  `version`, `superseded_by`, `human_verified` flags?),
- whether the API needs a "compare two element-source runs"
  endpoint shape from day one,
- how M4 (design-intent Q&A) cites elements back to source — if
  every element already carries `source + version + confidence` the
  citation surface is free.

**Note on naming.** [D-06](./decisions.md) generalizes "extraction"
to "element source" so the same provenance machinery covers extracted
*and* generated elements. Read references to `extraction_runs`
in earlier notes as `element_sources` going forward.

## Sources

| # | Source | Type | Notes |
|---|--------|------|-------|
|   |        |      |       |

## Findings

### Confidence representations in production tools

- …

### Extractor versioning patterns

- …

### Re-extraction UX

- …

### Human overrides

- …

### Audit / compliance

- …

## Implications for Atlas

- …

## Open follow-ups

- …

## Decision log entries closed by this note

- [ ] D-05 — Provenance model
