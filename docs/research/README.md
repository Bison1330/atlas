# M2 — Research

Pre-implementation research for **M2: Structured drawings** (geometry
extraction of rooms, walls, doors, windows from architectural sheets).

The goal is to ground our schema, our extraction strategy, and our
tooling choices in actual industry conventions before writing code.
M1 was a clean greenfield because PDF rasterization is a solved
problem; M2 isn't — there are competing standards (IFC, DXF entities,
COBie), competing approaches (rule-based vs deep learning vs hybrid),
and a deep ecosystem of OSS tools. Picking arbitrarily here costs us
months later.

## How this works

1. Each open research question gets a numbered note in this folder.
2. Notes start as stubs (the question + sub-questions); fill them in
   as the research lands.
3. When a note's findings close a decision, log the decision in
   [decisions.md](./decisions.md) — that's the durable record. Notes
   are working documents; the decision log is canonical.
4. Commit notes as they get filled in. Don't wait for "complete" —
   partial findings are useful, and a stale stub is worse than an
   honest "still investigating".

## Conventions

- **Filename:** `NN-topic-slug.md` (zero-padded 2-digit prefix).
- **Template:** copy [_template.md](./_template.md), fill in.
- **Sources:** every claim cites something — a spec, a paper, a repo,
  a vendor doc, an interview. "Industry common knowledge" is not a
  source; if it can't be cited it can't be relied on.
- **Confidence:** each finding is tagged `high` / `medium` / `low`.
  Nobody reading this later should have to guess how solid a claim is.

## Open notes

| #  | Topic                              | Status   |
|----|------------------------------------|----------|
| 01 | [Element schema standards](./01-element-schema-standards.md) | stub |
| 02 | [Extraction approaches](./02-extraction-approaches.md)       | stub |
| 03 | [OSS tooling survey](./03-tooling-survey.md)                 | stub |
| 04 | [Confidence + provenance](./04-confidence-and-provenance.md) | stub |

Milestone-specific research (not numbered — each milestone gets its
own prefix so they don't collide with the core M2 sequence):

| Topic | Status |
|-------|--------|
| [extractor-gaps.md](./extractor-gaps.md) — known M2/M3/M4 limits | living doc |
| [m4-phase3-ifc-probe.md](./m4-phase3-ifc-probe.md) — IFC static probe | answered |
| [m4-phase3-procurement.md](./m4-phase3-procurement.md) — real-drawing corpus punch list | answered |
| [m5-design-intent-qa.md](./m5-design-intent-qa.md) — Q&A scope, citation contract, eval plan | answered |
| [m6-annotations.md](./m6-annotations.md) — thin review slice: element annotations, no auth | answered |
| [m7-basic-auth.md](./m7-basic-auth.md) — basic email/password auth + drawing ownership | answered |
| [m8-projects.md](./m8-projects.md) — thin collaboration slice: projects + flat membership | in progress |

Add more as questions surface. Don't pre-create stubs we don't intend
to fill — empty research notes rot.

## Decisions ready to be made

These are blocked on the research above and need closing before M2
implementation starts. See [decisions.md](./decisions.md) for the
running list and what each one is waiting on.

## Strategy decisions

Separately from the M2-schema decisions, [decisions.md](./decisions.md)
also tracks open product/scope questions (currently **D-06**: the
expanded vision of Atlas as both an analytical *and* a generative
AEC platform). These don't block M2 — they shape it. Read D-06
before designing the provenance model so we don't bake in
extraction-only assumptions.
