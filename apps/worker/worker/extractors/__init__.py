"""Element-extraction libraries.

Pure functions that classify and validate building elements from raw
inputs (CAD layer names, line segments, arcs). Phase 3 will compose
these into a worker job that walks PDF/DXF/IFC content and produces
``Element`` rows; Phase 2 ships the libraries in isolation, fully
testable with synthetic inputs.

Three submodules:

- :mod:`ncs` — National CAD Standard layer-name parsing (the cheap
  classification signal: an entity on ``A-WALL-EXTR`` is almost
  certainly an exterior architectural wall).
- :mod:`geometry` — geometric validators that confirm or refute the
  NCS classification (parallel double-lines for walls, line+arc
  pairs for door swings, closed wall loops for rooms).
- :mod:`validation` — combine the above into per-element confidence
  scores that get persisted on ``Element.confidence``.
"""
