# Tier 1 — synthetic fixtures + ground-truth manifests

Ground-truth specs for the synthetic DXFs built by
`apps/worker/tests/fixtures/dxf_builders.py`. These are the
baseline cases the M3 evaluation runner regresses on every run —
they represent geometry we *built* and therefore know the answer to
exactly.

## File layout

| File | Purpose |
|------|---------|
| `*.manifest.yaml` | Ground-truth spec for one synthetic fixture |

A manifest references the fixture *by builder import path* rather
than mirroring a physical `.dxf` here — the fixture is
deterministic, so regenerating it at eval time keeps manifest +
geometry trivially in sync. Tier 2 / Tier 3 manifests will instead
reference a physical file path (since real CAD samples can't be
regenerated).

## Manifest schema

```yaml
name: three-room-floor              # short slug for reports
description: |                       # human prose; no parser meaning
  Two upper rooms over one lower room, T-junction at (5, 5).
fixture:
  kind: synthetic                    # synthetic | dxf-file | ifc-file
  builder: tests.fixtures.dxf_builders:build_three_room_floor
  # OR for tier 2/3:
  # path: tier2/revit-rac-advanced/exported-plan-l1.dxf

expected:
  elements:
    wall: { count: 6 }
    door: { count: 2 }
    room:
      count: 3                       # derived rooms from wall loops
      areas: [50.0, 25.0, 25.0]      # in DXF units²; sorted desc
      area_tolerance: 0.01           # fractional
  connectivity:
    hosted_doors: 2
    derived_rooms: 3
    adjacencies: 2

# Optional thresholds for the eval runner. Default is exact equality
# on counts, fractional tolerance on areas/lengths.
thresholds:
  count_exact: true
```

## Adding a new synthetic case

1. Add a builder to `apps/worker/tests/fixtures/dxf_builders.py`.
2. Drop a `<slug>.manifest.yaml` here.
3. The eval runner picks it up automatically (`scripts/eval_extraction.py`).
