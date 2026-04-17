"""DXF reader: walk a CAD drawing and emit element candidates.

Reads modelspace + every paperspace layout, classifies each entity
by its layer name (via the Phase 2 NCS parser), and yields
``ElementCandidate`` records ready for the orchestrator to persist.

Entity coverage:

- ``LINE``, open ``LWPOLYLINE``, and ``SPLINE`` on a wall layer →
  wall candidates with ``polyline`` geometry. SPLINE is flattened
  via :data:`SPLINE_FLATTEN_DISTANCE` (G-R1).
- Closed ``LWPOLYLINE`` on a room layer (A-ROOM / A-AREA / A-SPCE)
  → room candidates with ``polygon`` geometry.
- ``ARC`` on a door layer → door candidates with ``arc`` geometry.
- ``INSERT`` on a door / window / column layer → candidate of the
  matching kind using the insertion point as implied geometry
  (G-R3, option b). This is the dominant pattern in Revit /
  Archicad exports, where doors and windows are block references.
- ``LWPOLYLINE`` on a window layer → window candidate (G-C1).
- ``CIRCLE`` on a column layer → column candidates.

Anything else (annotations, dimensions, hatches) is collected as an
``OTHER`` candidate when its layer is well-formed NCS, and skipped
otherwise. Unknown layer names never raise — they just don't
produce candidates.

Confidence model (per element, before orchestrator persistence):

- NCS layer match score from
  :func:`worker.extractors.validation.score_ncs_match`.
- Geometric pass score (currently always 1.0 for the simple
  single-entity cases we cover; tightens in Phase 4).
- Aggregated via the ``product`` strategy.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ezdxf
import structlog
from atlas_core import ElementKind
from ezdxf.document import Drawing as DxfDocument

from worker.extractors import ncs, validation

log = structlog.get_logger("atlas.worker.extractors.dxf")

# IFC entity defaults per atlas ElementKind. Mirrors the common
# IfcWallStandardCase / IfcDoor / etc. mapping; orchestrator can
# override per element if a richer IFC type is known.
_IFC_DEFAULTS: dict[ElementKind, str] = {
    ElementKind.WALL: "IfcWallStandardCase",
    ElementKind.DOOR: "IfcDoor",
    ElementKind.WINDOW: "IfcWindow",
    ElementKind.COLUMN: "IfcColumn",
    ElementKind.STAIR: "IfcStair",
    ElementKind.ROOM: "IfcSpace",
}

# Element kinds that commonly ship as block references (INSERT) in
# Revit / Archicad exports. See G-R3 in docs/research/extractor-gaps.md.
_INSERT_KINDS: frozenset[ElementKind] = frozenset(
    {ElementKind.DOOR, ElementKind.WINDOW, ElementKind.COLUMN}
)

# Max distance (in drawing units) between a SPLINE and its polyline
# approximation. 0.01 is ~1 cm on metric plans and ~1/8" on
# imperial — tight enough to hug residential radii without exploding
# element count. See G-R1.
SPLINE_FLATTEN_DISTANCE: float = 0.01


@dataclass(slots=True)
class ElementCandidate:
    """Pre-persistence shape produced by the reader.

    The orchestrator turns each candidate into an ``Element`` row
    after it's chosen the ``source_id`` and ``sheet_id``.
    """

    kind: ElementKind
    geometry: dict[str, Any]
    bbox: dict[str, float] | None
    attrs: dict[str, Any]
    ifc_type: str | None
    ifc_properties: dict[str, dict[str, Any]]
    ncs_layer: str | None
    ncs_major_group: str | None
    ncs_minor_group: str | None
    source_layer: str
    confidence: float
    raw_handle: str | None = None  # DXF entity handle, for traceability


@dataclass(slots=True)
class DxfReadSummary:
    """What :func:`read_dxf` produced — useful for ``ElementSource.summary``."""

    candidates: list[ElementCandidate] = field(default_factory=list)
    layer_counts: dict[str, int] = field(default_factory=dict)
    skipped_entity_types: dict[str, int] = field(default_factory=dict)
    skipped_unknown_layers: int = 0


def read_dxf(path: Path) -> DxfReadSummary:
    """Open a DXF and produce element candidates.

    Always returns a :class:`DxfReadSummary` — the orchestrator
    decides how to react to zero candidates. Raises only when ezdxf
    can't open the file at all (corrupt / wrong version).
    """
    doc = ezdxf.readfile(str(path))
    summary = DxfReadSummary()

    for entity in _iter_all_entities(doc):
        layer_name = getattr(entity.dxf, "layer", "0")
        summary.layer_counts[layer_name] = summary.layer_counts.get(layer_name, 0) + 1

        candidates = _entity_to_candidates(entity, layer_name)
        if not candidates:
            etype = entity.dxftype()
            summary.skipped_entity_types[etype] = (
                summary.skipped_entity_types.get(etype, 0) + 1
            )
            layer = ncs.parse_layer(layer_name)
            if not layer.is_well_formed:
                summary.skipped_unknown_layers += 1
            continue

        summary.candidates.extend(candidates)

    log.info(
        "dxf.read_complete",
        path=str(path),
        candidates=len(summary.candidates),
        layers=len(summary.layer_counts),
    )
    return summary


def _iter_all_entities(doc: DxfDocument) -> Iterator[Any]:
    """Yield every entity in modelspace + every paperspace layout."""
    yield from doc.modelspace()
    for layout_name in doc.layout_names():
        if layout_name == "Model":
            continue
        yield from doc.layouts.get(layout_name)


def _entity_to_candidates(
    entity: Any, layer_name: str
) -> list[ElementCandidate]:
    """Map a single ezdxf entity to zero or more candidates."""
    layer = ncs.parse_layer(layer_name)
    if not layer.is_well_formed:
        return []

    kind = layer.element_kind
    if kind is None:
        return []

    etype = entity.dxftype()
    handle = getattr(entity.dxf, "handle", None)

    # Block references (INSERT) — treat the insertion point as the
    # implied geometry for kinds that commonly ship as blocks. We
    # don't flatten the block's internal entities; option (b) from
    # G-R3. Insertion point lands in geometry.center so downstream
    # door-hosting / connectivity still works.
    if etype == "INSERT" and kind in _INSERT_KINDS:
        return [
            _make_candidate(
                kind=kind,
                geometry=_insert_geometry(entity),
                attrs={
                    "source_entity": "INSERT",
                    "block_name": str(getattr(entity.dxf, "name", "") or ""),
                },
                layer=layer,
                handle=handle,
            )
        ]

    # Wall geometry: LINE, LWPOLYLINE, or SPLINE on a wall layer.
    if kind is ElementKind.WALL:
        if etype == "LINE":
            return [
                _make_candidate(
                    kind=ElementKind.WALL,
                    geometry=_line_geometry(entity),
                    attrs={"source_entity": "LINE"},
                    layer=layer,
                    handle=handle,
                )
            ]
        if etype == "LWPOLYLINE":
            return [
                _make_candidate(
                    kind=ElementKind.WALL,
                    geometry=_polyline_geometry(entity),
                    attrs={
                        "source_entity": "LWPOLYLINE",
                        "closed": bool(entity.closed),
                    },
                    layer=layer,
                    handle=handle,
                )
            ]
        if etype == "SPLINE":
            pts = _spline_to_points(entity)
            if len(pts) < 2:
                return []
            return [
                _make_candidate(
                    kind=ElementKind.WALL,
                    geometry={"kind": "polyline", "points": pts},
                    attrs={
                        "source_entity": "SPLINE",
                        "flatten_distance": SPLINE_FLATTEN_DISTANCE,
                        "vertex_count": len(pts),
                    },
                    layer=layer,
                    handle=handle,
                )
            ]
        return []

    # Room boundary: closed LWPOLYLINE on a room layer.
    if kind is ElementKind.ROOM:
        if etype == "LWPOLYLINE" and entity.closed:
            return [
                _make_candidate(
                    kind=ElementKind.ROOM,
                    geometry=_polygon_geometry(entity),
                    attrs={"source_entity": "LWPOLYLINE"},
                    layer=layer,
                    handle=handle,
                )
            ]
        return []

    # Door swing: ARC on a door layer (block-ref case handled above).
    if kind is ElementKind.DOOR:
        if etype == "ARC":
            return [
                _make_candidate(
                    kind=ElementKind.DOOR,
                    geometry=_arc_geometry(entity),
                    attrs={
                        "source_entity": "ARC",
                        "swing_angle_deg": _arc_sweep_deg(entity),
                    },
                    layer=layer,
                    handle=handle,
                )
            ]
        return []

    # Window: LWPOLYLINE on a window layer (block-ref case handled
    # above). Sill/jamb lines are out of scope until a real fixture
    # needs them — see G-C1.
    if kind is ElementKind.WINDOW:
        if etype == "LWPOLYLINE":
            closed = bool(entity.closed)
            geometry = (
                _polygon_geometry(entity) if closed else _polyline_geometry(entity)
            )
            return [
                _make_candidate(
                    kind=ElementKind.WINDOW,
                    geometry=geometry,
                    attrs={
                        "source_entity": "LWPOLYLINE",
                        "closed": closed,
                    },
                    layer=layer,
                    handle=handle,
                )
            ]
        return []

    # Columns: CIRCLE (block-ref case handled above).
    if kind is ElementKind.COLUMN:
        if etype == "CIRCLE":
            return [
                _make_candidate(
                    kind=ElementKind.COLUMN,
                    geometry=_circle_geometry(entity),
                    attrs={"source_entity": "CIRCLE"},
                    layer=layer,
                    handle=handle,
                )
            ]
        return []

    # Catch-all: layer is well-formed NCS but not a kind we have
    # special handling for. Capture as OTHER so downstream queries
    # can still see it.
    if kind is ElementKind.OTHER:
        return [
            _make_candidate(
                kind=ElementKind.OTHER,
                geometry={"kind": "raw", "entity_type": etype},
                attrs={"source_entity": etype},
                layer=layer,
                handle=handle,
            )
        ]

    return []


# ---------- geometry shape helpers ----------


def _line_geometry(entity: Any) -> dict[str, Any]:
    a, b = entity.dxf.start, entity.dxf.end
    return {
        "kind": "polyline",
        "points": [
            {"x": float(a.x), "y": float(a.y)},
            {"x": float(b.x), "y": float(b.y)},
        ],
    }


def _polyline_geometry(entity: Any) -> dict[str, Any]:
    points = [
        {"x": float(p[0]), "y": float(p[1])} for p in entity.get_points("xy")
    ]
    return {"kind": "polyline", "points": points}


def _polygon_geometry(entity: Any) -> dict[str, Any]:
    points = [
        {"x": float(p[0]), "y": float(p[1])} for p in entity.get_points("xy")
    ]
    return {"kind": "polygon", "ring": points}


def _arc_geometry(entity: Any) -> dict[str, Any]:
    c = entity.dxf.center
    return {
        "kind": "arc",
        "center": {"x": float(c.x), "y": float(c.y)},
        "radius": float(entity.dxf.radius),
        "start_angle_deg": float(entity.dxf.start_angle),
        "end_angle_deg": float(entity.dxf.end_angle),
    }


def _circle_geometry(entity: Any) -> dict[str, Any]:
    c = entity.dxf.center
    return {
        "kind": "circle",
        "center": {"x": float(c.x), "y": float(c.y)},
        "radius": float(entity.dxf.radius),
    }


def _insert_geometry(entity: Any) -> dict[str, Any]:
    """Insertion point + scale/rotation for a block reference.

    We don't flatten the block's interior — the insertion point is
    all we need for door-hosting and for placing the element on the
    sheet. ``center`` is named to match ``_arc_geometry`` so the
    connectivity code's ``geometry.get("center")`` lookup works
    uniformly for block-based and arc-based doors.
    """
    ins = entity.dxf.insert
    return {
        "kind": "insert",
        "center": {"x": float(ins.x), "y": float(ins.y)},
        "rotation_deg": float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
        "x_scale": float(getattr(entity.dxf, "xscale", 1.0) or 1.0),
        "y_scale": float(getattr(entity.dxf, "yscale", 1.0) or 1.0),
    }


def _spline_to_points(entity: Any) -> list[dict[str, float]]:
    """Flatten a SPLINE into a polyline approximation.

    ezdxf's ``Spline.flattening(distance)`` yields points along the
    curve such that no point is farther than ``distance`` from the
    true spline. Returns an empty list if the entity can't be
    flattened (malformed control/knot vector).
    """
    try:
        vertices = list(entity.flattening(SPLINE_FLATTEN_DISTANCE))
    except Exception:
        return []
    return [{"x": float(v.x), "y": float(v.y)} for v in vertices]


def _arc_sweep_deg(entity: Any) -> float:
    """ezdxf stores ARC angles in degrees CCW; sweep is end - start mod 360."""
    sweep = float(entity.dxf.end_angle) - float(entity.dxf.start_angle)
    return sweep % 360.0


# ---------- candidate construction ----------


def _make_candidate(
    *,
    kind: ElementKind,
    geometry: dict[str, Any],
    attrs: dict[str, Any],
    layer: ncs.NcsLayer,
    handle: str | None,
) -> ElementCandidate:
    bbox = _bbox_of(geometry)
    confidence = validation.aggregate_confidence(
        [
            validation.score_ncs_match(layer, kind),
            validation.score_geometric_validation(passed=True, slack=0.0),
        ],
        method="product",
    )
    return ElementCandidate(
        kind=kind,
        geometry=geometry,
        bbox=bbox,
        attrs=attrs,
        ifc_type=_IFC_DEFAULTS.get(kind),
        ifc_properties={},
        ncs_layer=layer.raw,
        ncs_major_group=layer.major_group,
        ncs_minor_group=layer.minor_group,
        source_layer=layer.raw,
        confidence=confidence,
        raw_handle=handle,
    )


def _bbox_of(geometry: dict[str, Any]) -> dict[str, float] | None:
    """Compute bbox from any of our geometry shapes; None for shapes
    we can't summarize without more math."""
    g = geometry.get("kind")
    pts: list[tuple[float, float]] = []

    if g in ("polyline", "polygon"):
        seq = geometry.get("points") if g == "polyline" else geometry.get("ring")
        pts = [(p["x"], p["y"]) for p in (seq or [])]
    elif g == "arc":
        # Conservative: use the bounding square of the full circle.
        c = geometry["center"]
        r = geometry["radius"]
        pts = [(c["x"] - r, c["y"] - r), (c["x"] + r, c["y"] + r)]
    elif g == "circle":
        c = geometry["center"]
        r = geometry["radius"]
        pts = [(c["x"] - r, c["y"] - r), (c["x"] + r, c["y"] + r)]

    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}
