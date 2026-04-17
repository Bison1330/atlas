# Test corpus

Real-world architectural drawings used to validate the M2 extractor
and downstream M3 analyses against authentic CAD authoring (rather
than just synthetic ezdxf fixtures generated in test code).

## Tiers

The corpus is split by *trust* and *redistribution*:

| Tier  | Purpose                                          | Distribution                       |
|-------|--------------------------------------------------|------------------------------------|
| **1** | Smoke samples — small, well-known, used in CI    | Public, redistributable; committed |
| **2** | Production-realistic — multi-system, multi-sheet | Vendor-licensed; **not committed** |
| **3** | Edge cases — malformed, legacy, vendor quirks    | Mixed; per-file note in MANIFEST   |

The split matters because Tier 2 includes Autodesk / Graphisoft
samples that ship under their respective trial / educational
licenses and can't sit in a public git repo. Tier 1 is what CI
actually exercises; Tier 2/3 are local-only validation.

## What's in here today

See [`MANIFEST.md`](./MANIFEST.md) for the full target inventory and
the *current* status of each file (committed vs. external).

Short version: the corpus is **mostly empty** — most listed sources
require interactive sign-in / EULA acceptance / browser navigation
and can't be fetched from this CLI. Files have to be downloaded
manually and dropped into the matching tier directory; the
`MANIFEST.md` documents the expected paths and licensing so you can
do that without losing track.

## Why files aren't auto-fetched

Cataloging the constraints honestly so future-me doesn't try and
fail again:

- **Autodesk Revit samples (rac_advanced, Snowdon Towers, Technical
  School)** — distributed *with* Revit, not as standalone CAD
  downloads. Requires Autodesk account + Revit install or trial.
- **Graphisoft Hillside House** — Archicad sample; same story,
  account + Archicad install.
- **buildingSMART IFC test files** — these *are* publicly mirrored
  on GitHub, but URLs change and the catalog is large; safer to
  pick specific files by hand than auto-mirror.
- **Municipal permit portals** (Seattle SDCI, Portland BDS, SF DBI)
  — search-driven UIs, no stable direct-download URLs, often
  rate-limited; manual export is the only reliable path.

## Adding a file

1. Drop it under the matching tier directory.
2. Add a row to `MANIFEST.md` with: filename, source URL, license,
   one-line description, and what it's *good for* (which extractor /
   algorithm it stresses).
3. If Tier 2 / 3 (not committed): the `.gitignore` keeps it out of
   git automatically. Don't `git add -f` it.

## How tests use it

Tier 1 fixtures are referenced by path in test code; missing files
cause those tests to **skip**, not fail (a contributor without the
full corpus should still be able to run the suite). Synthetic
fixtures generated programmatically via `ezdxf` continue to be the
default for unit tests — the corpus is for integration validation.
