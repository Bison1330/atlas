# buildingSMART PCERT Sample Scene — IFC 4.0.2.1

Three IFC files from buildingSMART's official PCERT (private
certification) sample scene, downloaded for use as Atlas reference
inputs once the M2 IFC reader lands.

## Files in this directory

| Filename                                          | Bytes     | Discipline      |
|---------------------------------------------------|-----------|-----------------|
| `buildingsmart-pcert-building-architecture.ifc`   | 225,635   | Architectural   |
| `buildingsmart-pcert-building-hvac.ifc`           | 179,727   | HVAC            |
| `buildingsmart-pcert-building-structural.ifc`     | 296,640   | Structural      |

All three describe the same building from different disciplines —
useful for testing multi-system extraction once we have it.

## Source

- **Repo:** https://github.com/buildingSMART/Sample-Test-Files
- **Path:** `IFC 4.0.2.1 (IFC 4)/PCERT-Sample-Scene/`
- **Originals (preserved upstream filenames):** `Building-Architecture.ifc`,
  `Building-Hvac.ifc`, `Building-Structural.ifc`. Local files are
  prefixed `buildingsmart-pcert-` and lowercased so multiple-source
  corpora don't collide.
- **Retrieved:** 2026-04-17 via `curl` from `raw.githubusercontent.com`.
- **License:** Per the repo's `LICENSE` file (Apache-2.0; verified at
  fetch time). Apache-2.0 permits redistribution with attribution.

## Status in Atlas

- ❌ **Not currently parseable** — Atlas's M2 extractor is DXF-only.
  An IFC reader is on the roadmap but unscheduled.
- ✅ **Useful as a "what realistic IFC looks like" reference** for
  designing the eventual reader (entity types, property sets, units,
  georeferencing — the file's header declares `IFC4`,
  `IFCPROJECTEDCRS('EPSG:32760')`, `IFCSIUNIT(...,.MILLI.,.METRE.)`,
  good real-world signal).
- 🟡 **Out of `.gitignore` scope** — these live under
  `tests/fixtures/corpus/tier3/`, which `.gitignore`s the file
  contents. Re-fetch via the script below if a fresh clone needs
  them.

## Re-fetch script

```bash
cd /opt/atlas/tests/fixtures/corpus/tier3
BASE='https://raw.githubusercontent.com/buildingSMART/Sample-Test-Files/main/IFC%204.0.2.1%20%28IFC%204%29/PCERT-Sample-Scene'
for f in Building-Architecture.ifc Building-Hvac.ifc Building-Structural.ifc; do
  curl -fsSL -o "buildingsmart-pcert-${f,,}" "$BASE/$f"
done
```

## Anonymization

Not required — the buildingSMART originals are synthetic
demonstration content. No owner / address / occupant metadata to
strip.
