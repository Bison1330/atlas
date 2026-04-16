# atlas-core

Shared Python domain model for Atlas.

Defines the **structured drawing** representation — a schema-typed view of an architectural sheet broken down into elements (rooms, walls, doors, windows, dimensions, annotations).

This package is intentionally dependency-light: Pydantic v2 only. It is imported by the API, the worker, and any downstream analyzer that reasons over drawings.

## Public API

```python
from atlas_core import (
    StructuredDrawing, StructuredSheet, DrawingElement,
    Room, Wall, Door, Window,
    Point, Polyline, Polygon, BoundingBox,
    ElementKind, Units, SheetDiscipline,
)
```

See `atlas_core/models.py` for the full schema.
