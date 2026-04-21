"""3D scene reconstruction from a StructuredSheet.

Consumes the already-extracted 2D elements (walls as polyline
centerlines, doors/windows with ``host_wall_id``, rooms as polygons)
and produces a ``Scene3D`` — a Three.js-ready bundle of wall meshes
(with door/window voids cut), floor slabs, and opening metadata.

This module is the pure-geometry layer: no FastAPI, no DB, no React.
A sheet goes in, a JSON-serialisable Pydantic model comes out.

Hosting is not re-derived here. By the time a ``StructuredSheet``
reaches us, ``connectivity.host_walls_for_doors`` has already run
upstream and its verdict lives on ``Door.host_wall_id``. We only
need to decide *where along* that wall the opening sits — and even
that can be short-circuited by an extractor-supplied
``properties["parametric_position"]``.
"""

from __future__ import annotations

import logging
import math
from typing import Literal
from uuid import UUID

import numpy as np
import shapely.geometry as sg
import trimesh
import trimesh.boolean
import trimesh.creation
from pydantic import BaseModel, ConfigDict, Field

# ``manifold3d`` is load-bearing in two places, neither of which shows
# up in a static import scan of this file:
#
# 1. Wall/opening booleans call ``trimesh.boolean.difference`` and
#    ``trimesh.boolean.union`` with ``engine="manifold"``.
# 2. Floor triangulation calls ``trimesh.creation.triangulate_polygon``
#    with ``engine="manifold"`` — the other engines trimesh ships
#    (``earcut`` / ``triangle``) require extra pip packages that we
#    deliberately do not depend on.
#
# If a future dependency update drops manifold3d, both floors and wall
# voids silently regress. Fail loudly at import time instead.
try:
    import manifold3d  # noqa: F401
except ImportError as e:  # pragma: no cover - env-level failure
    raise ImportError(
        "reconstruct3d requires manifold3d for both boolean operations "
        "(wall/opening differences) and polygon triangulation (floor slabs). "
        "Install with: pip install manifold3d>=2.5"
    ) from e

from atlas_core.enums import ElementKind, Units
from atlas_core.geometry import Polygon as AtlasPolygon
from atlas_core.geometry import Polyline
from atlas_core.models import Door, Room, StructuredSheet, Wall, Window

log = logging.getLogger(__name__)

_UNIT_TO_METERS: dict[Units, float] = {
    Units.MILLIMETERS: 0.001,
    Units.CENTIMETERS: 0.01,
    Units.METERS: 1.0,
    Units.INCHES: 0.0254,
    Units.FEET: 0.3048,
}

# Tolerance used when deciding whether a wall segment lies on a room
# boundary (meters, post-normalisation).
_ROOM_BOUNDARY_TOL_M: float = 0.1

# Z-offset for floor slabs to avoid z-fighting with a ground plane
# the frontend may render underneath.
_FLOOR_Z_OFFSET_M: float = 0.001


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class BBox3(BaseModel):
    """Axis-aligned 3D bounding box as two [x, y, z] arrays."""

    model_config = ConfigDict(frozen=True)

    min: list[float] = Field(min_length=3, max_length=3)
    max: list[float] = Field(min_length=3, max_length=3)


class WallMesh(BaseModel):
    """A single wall-segment mesh.

    One parent ``Wall`` may produce multiple ``WallMesh`` entries if
    its centerline has more than two points (e.g. an L-shaped wall).
    ``parent_wall_id`` lets the UI group segments back together.
    """

    id: str
    parent_wall_id: str
    vertices: list[float]  # flat [x0,y0,z0, x1,y1,z1, ...]
    indices: list[int]     # flat [i0,i1,i2, ...]
    room_ids: list[str]


class FloorSlab(BaseModel):
    """A triangulated floor for one room, sitting just above z=0."""

    room_id: str
    name: str | None
    vertices: list[float]
    indices: list[int]
    centroid: list[float] = Field(min_length=3, max_length=3)
    area_m2: float


class Opening(BaseModel):
    """Metadata for a placed door/window.

    The hole is already cut into the wall mesh. This record exists
    so the UI can position click-targets, tooltips, and highlights
    — and so consumers can tell that a specific opening failed to
    be booleaned into its wall (``failed=True``).
    """

    id: str
    kind: Literal["door", "window"]
    wall_id: str
    room_ids: list[str]
    bbox: BBox3
    failed: bool = False


class Scene3D(BaseModel):
    """Top-level scene bundle for the frontend."""

    units: Literal["m"] = "m"
    bbox: BBox3
    walls: list[WallMesh] = Field(default_factory=list)
    floors: list[FloorSlab] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def reconstruct_sheet(
    sheet: StructuredSheet,
    *,
    default_wall_thickness_m: float = 0.15,
    default_wall_height_m: float = 2.74,
    default_door_height_m: float = 2.03,
    default_window_height_m: float = 1.22,
    default_window_sill_m: float = 0.91,
) -> Scene3D:
    """Reconstruct a 3D scene from a single structured sheet."""

    scale = _UNIT_TO_METERS[sheet.units]

    walls = [e for e in sheet.elements if isinstance(e, Wall)]
    doors = [e for e in sheet.elements if isinstance(e, Door)]
    windows = [e for e in sheet.elements if isinstance(e, Window)]
    rooms = [e for e in sheet.elements if isinstance(e, Room)]

    wall_polylines_m = {w.id: _scale_polyline(w.centerline, scale) for w in walls}
    room_polygons_m = {r.id: _polygon_to_shapely(r.boundary, scale) for r in rooms}

    # Group openings by host wall UUID. Drop openings without a host —
    # there's nowhere to place them.
    openings_by_wall: dict[UUID, list[Door | Window]] = {}
    for op in (*doors, *windows):
        if op.host_wall_id is None:
            continue
        openings_by_wall.setdefault(op.host_wall_id, []).append(op)

    wall_meshes: list[WallMesh] = []
    opening_records: list[Opening] = []
    all_trimesh_pieces: list[trimesh.Trimesh] = []

    # --- Walls + openings ----------------------------------------------------
    for wall in walls:
        centerline_m = wall_polylines_m[wall.id]
        segments = _split_polyline(centerline_m)
        if not segments:
            continue

        total_length = sum(_seg_length(s) for s in segments)
        cum_lengths = _cumulative_lengths(segments)

        thickness = (wall.thickness * scale) if wall.thickness else default_wall_thickness_m
        height = (wall.height * scale) if wall.height else default_wall_height_m

        wall_openings = openings_by_wall.get(wall.id, [])
        placements = _place_openings_on_segments(
            wall_openings,
            centerline_m,
            segments,
            cum_lengths,
            total_length,
            scale,
            default_door_height_m=default_door_height_m,
            default_window_height_m=default_window_height_m,
            default_window_sill_m=default_window_sill_m,
        )

        for seg_idx, (p0, p1) in enumerate(segments):
            seg_placements = [p for p in placements if p.segment_index == seg_idx]
            seg_room_ids = _segment_room_ids(
                p0, p1, room_polygons_m, tol=_ROOM_BOUNDARY_TOL_M
            )

            mesh, failed_opening_ids = _build_wall_segment_mesh(
                p0=p0,
                p1=p1,
                thickness=thickness,
                height=height,
                openings=seg_placements,
            )

            if mesh is not None and len(mesh.vertices) > 0:
                all_trimesh_pieces.append(mesh)
                wall_meshes.append(
                    WallMesh(
                        id=f"{wall.id}#{seg_idx}",
                        parent_wall_id=str(wall.id),
                        vertices=np.asarray(mesh.vertices, dtype=float)
                        .flatten()
                        .tolist(),
                        indices=np.asarray(mesh.faces, dtype=int).flatten().tolist(),
                        room_ids=[str(rid) for rid in seg_room_ids],
                    )
                )

            for p in seg_placements:
                opening_records.append(
                    Opening(
                        id=str(p.opening.id),
                        kind="door" if isinstance(p.opening, Door) else "window",
                        wall_id=str(wall.id),
                        room_ids=[str(rid) for rid in seg_room_ids],
                        bbox=p.world_bbox,
                        failed=p.opening.id in failed_opening_ids,
                    )
                )

    # --- Floors --------------------------------------------------------------
    floor_slabs: list[FloorSlab] = []
    for room in rooms:
        poly = room_polygons_m[room.id]
        if poly.is_empty or poly.area <= 0:
            continue
        try:
            # engine="manifold" requires the manifold3d package. The
            # import-time guard at the top of this module enforces it.
            verts_2d, faces = trimesh.creation.triangulate_polygon(poly, engine="manifold")
        except Exception as e:
            log.warning("floor triangulation failed for room %s: %s", room.id, e)
            continue

        verts_3d = np.column_stack(
            [verts_2d[:, 0], verts_2d[:, 1], np.full(len(verts_2d), _FLOOR_Z_OFFSET_M)]
        )
        floor_mesh = trimesh.Trimesh(vertices=verts_3d, faces=faces, process=False)
        all_trimesh_pieces.append(floor_mesh)

        centroid = poly.centroid
        floor_slabs.append(
            FloorSlab(
                room_id=str(room.id),
                name=room.name,
                vertices=verts_3d.flatten().tolist(),
                indices=np.asarray(faces, dtype=int).flatten().tolist(),
                centroid=[float(centroid.x), float(centroid.y), _FLOOR_Z_OFFSET_M],
                area_m2=float(poly.area),
            )
        )

    # --- Scene bbox ----------------------------------------------------------
    scene_bbox = _union_bbox(all_trimesh_pieces)

    return Scene3D(
        units="m",
        bbox=scene_bbox,
        walls=wall_meshes,
        floors=floor_slabs,
        openings=opening_records,
    )


# ---------------------------------------------------------------------------
# Geometry helpers — unit scaling & polyline math
# ---------------------------------------------------------------------------


def _scale_polyline(pl: Polyline, scale: float) -> list[tuple[float, float]]:
    return [(pt.x * scale, pt.y * scale) for pt in pl.points]


def _polygon_to_shapely(poly: AtlasPolygon, scale: float) -> sg.Polygon:
    ring = [(pt.x * scale, pt.y * scale) for pt in poly.ring]
    holes = [[(pt.x * scale, pt.y * scale) for pt in h] for h in poly.holes]
    sp = sg.Polygon(ring, holes)
    # Fix orientation / self-touches without changing geometry meaningfully.
    if not sp.is_valid:
        sp = sp.buffer(0)
    return sp


def _split_polyline(
    points: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Turn an N-point polyline into N-1 straight segments.

    Zero-length segments (duplicate consecutive points) are dropped —
    they contribute no geometry and would produce degenerate boxes.
    """

    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(len(points) - 1):
        p0, p1 = points[i], points[i + 1]
        if _seg_length((p0, p1)) > 0:
            out.append((p0, p1))
    return out


def _seg_length(seg: tuple[tuple[float, float], tuple[float, float]]) -> float:
    (x0, y0), (x1, y1) = seg
    return math.hypot(x1 - x0, y1 - y0)


def _cumulative_lengths(
    segments: list[tuple[tuple[float, float], tuple[float, float]]]
) -> list[float]:
    """Returns [0, len(s0), len(s0)+len(s1), ...] — (N+1) values for N segs."""
    out = [0.0]
    acc = 0.0
    for s in segments:
        acc += _seg_length(s)
        out.append(acc)
    return out


# ---------------------------------------------------------------------------
# Opening placement along a polyline
# ---------------------------------------------------------------------------


class _OpeningPlacement:
    """Resolved placement of one opening on one wall segment."""

    __slots__ = (
        "opening",
        "segment_index",
        "local_t",
        "opening_width_m",
        "opening_height_m",
        "sill_height_m",
        "world_bbox",
    )

    def __init__(
        self,
        opening: Door | Window,
        segment_index: int,
        local_t: float,
        opening_width_m: float,
        opening_height_m: float,
        sill_height_m: float,
        world_bbox: BBox3,
    ) -> None:
        self.opening = opening
        self.segment_index = segment_index
        self.local_t = local_t
        self.opening_width_m = opening_width_m
        self.opening_height_m = opening_height_m
        self.sill_height_m = sill_height_m
        self.world_bbox = world_bbox


def _place_openings_on_segments(
    openings: list[Door | Window],
    centerline_m: list[tuple[float, float]],
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    cum_lengths: list[float],
    total_length: float,
    scale: float,
    *,
    default_door_height_m: float,
    default_window_height_m: float,
    default_window_sill_m: float,
) -> list[_OpeningPlacement]:
    placements: list[_OpeningPlacement] = []
    if total_length <= 0 or not segments:
        return placements

    for op in openings:
        param = _parametric_position_for(op, centerline_m, scale)
        if param is None:
            continue
        param = min(max(param, 0.0), 1.0)
        abs_pos = param * total_length
        seg_idx, local_t = _locate_segment(cum_lengths, abs_pos)

        width = op.width * scale
        if isinstance(op, Door):
            height = (op.height * scale) if op.height else default_door_height_m
            sill = 0.0
        else:  # Window
            height = (op.height * scale) if op.height else default_window_height_m
            sill = (op.sill_height * scale) if op.sill_height else default_window_sill_m

        world_bbox = _opening_world_bbox(
            segments[seg_idx], local_t, width, height, sill
        )
        placements.append(
            _OpeningPlacement(
                opening=op,
                segment_index=seg_idx,
                local_t=local_t,
                opening_width_m=width,
                opening_height_m=height,
                sill_height_m=sill,
                world_bbox=world_bbox,
            )
        )
    return placements


def _parametric_position_for(
    op: Door | Window,
    centerline_m: list[tuple[float, float]],
    scale: float,
) -> float | None:
    """Return the opening's parametric position on its host wall, or None.

    Preference order:
    1. Extractor-supplied ``properties["parametric_position"]`` (already
       unit-free — it's a ratio).
    2. Projection of the opening's bbox center (in sheet units → meters
       via ``scale``) onto the wall centerline.
    3. Unplaceable → None.
    """
    raw = op.properties.get("parametric_position")
    if isinstance(raw, int | float):
        return float(raw)

    if op.bbox is None:
        return None
    cx = 0.5 * (op.bbox.minx + op.bbox.maxx) * scale
    cy = 0.5 * (op.bbox.miny + op.bbox.maxy) * scale
    return _project_point_to_polyline((cx, cy), centerline_m)


def _project_point_to_polyline(
    p: tuple[float, float], points: list[tuple[float, float]]
) -> float | None:
    """Return parametric position (0..1) of p's nearest point on the polyline."""

    if len(points) < 2:
        return None
    total = 0.0
    lengths: list[float] = []
    for i in range(len(points) - 1):
        ln = math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        lengths.append(ln)
        total += ln
    if total == 0:
        return None

    best_dist = float("inf")
    best_abs = 0.0
    acc = 0.0
    for i, ln in enumerate(lengths):
        if ln == 0:
            continue
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        t = ((p[0] - x0) * dx + (p[1] - y0) * dy) / (ln * ln)
        t = max(0.0, min(1.0, t))
        cx, cy = x0 + t * dx, y0 + t * dy
        d = math.hypot(p[0] - cx, p[1] - cy)
        if d < best_dist:
            best_dist = d
            best_abs = acc + t * ln
        acc += ln

    return best_abs / total


def _locate_segment(cum_lengths: list[float], abs_pos: float) -> tuple[int, float]:
    """Given cumulative segment lengths, return (segment_index, local_t in [0,1])."""
    n = len(cum_lengths) - 1  # number of segments
    # Clamp to the valid range.
    if abs_pos <= 0:
        return 0, 0.0
    if abs_pos >= cum_lengths[-1]:
        return n - 1, 1.0
    for i in range(n):
        lo, hi = cum_lengths[i], cum_lengths[i + 1]
        if lo <= abs_pos <= hi:
            seg_len = hi - lo
            t = (abs_pos - lo) / seg_len if seg_len > 0 else 0.0
            return i, t
    # Fallback — shouldn't reach here.
    return n - 1, 1.0


# ---------------------------------------------------------------------------
# Wall segment mesh construction
# ---------------------------------------------------------------------------


def _segment_transform(
    p0: tuple[float, float], p1: tuple[float, float]
) -> np.ndarray:
    """4×4 transform taking local frame (x along segment, y normal, z up)
    with origin at the segment midpoint → world.
    """
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return np.eye(4)
    cos_a = dx / length
    sin_a = dy / length
    cx = 0.5 * (p0[0] + p1[0])
    cy = 0.5 * (p0[1] + p1[1])
    return np.array(
        [
            [cos_a, -sin_a, 0.0, cx],
            [sin_a,  cos_a, 0.0, cy],
            [0.0,    0.0,   1.0, 0.0],
            [0.0,    0.0,   0.0, 1.0],
        ]
    )


def _build_wall_segment_mesh(
    *,
    p0: tuple[float, float],
    p1: tuple[float, float],
    thickness: float,
    height: float,
    openings: list[_OpeningPlacement],
) -> tuple[trimesh.Trimesh | None, set[UUID]]:
    """Build one wall-segment solid with opening voids subtracted.

    Returns ``(mesh, failed_opening_ids)``. If the boolean fails
    catastrophically we emit the uncut wall and mark every opening on
    this segment as failed — the brief's rule: "never throw".
    """
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if length == 0 or thickness <= 0 or height <= 0:
        return None, {o.opening.id for o in openings}

    wall_local = trimesh.creation.box(extents=(length, thickness, height))
    wall_local.apply_translation([0.0, 0.0, height / 2.0])

    transform = _segment_transform(p0, p1)

    subtractors: list[trimesh.Trimesh] = []
    for op in openings:
        sub = trimesh.creation.box(
            extents=(op.opening_width_m, thickness + 0.02, op.opening_height_m)
        )
        x_center = op.local_t * length - length / 2.0
        z_center = op.sill_height_m + op.opening_height_m / 2.0
        sub.apply_translation([x_center, 0.0, z_center])
        subtractors.append(sub)

    if not subtractors:
        wall_local.apply_transform(transform)
        return wall_local, set()

    try:
        # engine="manifold" requires the manifold3d package. The
        # import-time guard at the top of this module enforces it.
        if len(subtractors) == 1:
            cut = trimesh.boolean.difference(
                [wall_local, subtractors[0]], engine="manifold"
            )
        else:
            voids_union = trimesh.boolean.union(subtractors, engine="manifold")
            cut = trimesh.boolean.difference([wall_local, voids_union], engine="manifold")

        if cut is None or len(cut.vertices) == 0 or len(cut.faces) == 0:
            raise ValueError("boolean produced an empty mesh")

        cut.apply_transform(transform)
        return cut, set()
    except Exception as e:  # pragma: no cover - logged fallback path
        log.warning(
            "wall boolean failed (length=%.3f, thickness=%.3f, %d openings): %s",
            length,
            thickness,
            len(subtractors),
            e,
        )
        wall_local.apply_transform(transform)
        return wall_local, {o.opening.id for o in openings}


# ---------------------------------------------------------------------------
# Bounding boxes
# ---------------------------------------------------------------------------


def _opening_world_bbox(
    segment: tuple[tuple[float, float], tuple[float, float]],
    local_t: float,
    width: float,
    height: float,
    sill: float,
) -> BBox3:
    """World-space axis-aligned bbox of an opening's subtractor box."""
    p0, p1 = segment
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    transform = _segment_transform(p0, p1)
    # The subtractor is a box centered at (local_t*length - length/2,
    # 0, sill + height/2) with extents (width, *, height). Use a
    # slightly-bigger-than-zero y extent so the bbox has depth.
    box = trimesh.creation.box(extents=(width, 0.01, height))
    x_center = local_t * length - length / 2.0
    z_center = sill + height / 2.0
    box.apply_translation([x_center, 0.0, z_center])
    box.apply_transform(transform)
    mins = box.vertices.min(axis=0)
    maxs = box.vertices.max(axis=0)
    return BBox3(
        min=[float(mins[0]), float(mins[1]), float(mins[2])],
        max=[float(maxs[0]), float(maxs[1]), float(maxs[2])],
    )


def _union_bbox(pieces: list[trimesh.Trimesh]) -> BBox3:
    if not pieces:
        return BBox3(min=[0.0, 0.0, 0.0], max=[0.0, 0.0, 0.0])
    mins = np.array([p.vertices.min(axis=0) for p in pieces]).min(axis=0)
    maxs = np.array([p.vertices.max(axis=0) for p in pieces]).max(axis=0)
    return BBox3(
        min=[float(mins[0]), float(mins[1]), float(mins[2])],
        max=[float(maxs[0]), float(maxs[1]), float(maxs[2])],
    )


# ---------------------------------------------------------------------------
# Room-membership for wall segments
# ---------------------------------------------------------------------------


def _segment_room_ids(
    p0: tuple[float, float],
    p1: tuple[float, float],
    room_polygons: dict[UUID, sg.Polygon],
    *,
    tol: float,
) -> list[UUID]:
    """Return ids of rooms whose boundary the segment approximately lies on.

    Criterion (per the spec): ``poly.boundary.distance(segment) < tol``.
    To guard against the corner-touch false positive — a wall that only
    grazes the room at a single vertex — also require the segment's
    midpoint to sit within ``tol`` of the boundary.
    """
    seg = sg.LineString([p0, p1])
    midpoint = sg.Point(0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1]))
    hits: list[UUID] = []
    for rid, poly in room_polygons.items():
        if poly.is_empty:
            continue
        boundary = poly.boundary
        if boundary.distance(seg) <= tol and boundary.distance(midpoint) <= tol:
            hits.append(rid)
    return hits
