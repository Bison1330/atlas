"""ORM-Element → ``StructuredSheet`` translator for 3D reconstruction.

Pure-function layer with no DB or FastAPI imports, designed for unit
testing in isolation. Sits between what the DXF extractor *actually*
writes (sometimes sparse — no width on INSERT doors, no bbox on INSERT
windows, no thickness on most walls) and what
:func:`atlas_core.reconstruct3d.reconstruct_sheet` *requires* (the
strict ``atlas_core.models`` shape, which rejects missing widths at
validation time).

We deliberately keep the data model strict and fix the gap here. The
alternatives (relaxing ``Door.width`` or extending the extractor to
resolve INSERT block geometry) were considered and rejected for the
scope of the 3D walkthrough series:

- Relaxing the model would let extractor bugs propagate silently.
- Widening the extractor to compute INSERT bboxes from block
  definitions is a multi-session change to the extraction layer.

This translator is the explicit "what the extractor happened to
produce" ↔ "what downstream assumes" boundary. Each time a default
kicks in we log + count it. When the extractor is eventually widened
the counts should drop to zero and this helper can be retired cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import shapely.geometry as sg
import structlog

from atlas_core.enums import ElementKind
from atlas_core.geometry import BoundingBox, Point, Polygon, Polyline
from atlas_core.models import Door, Room, StructuredSheet, Wall, Window
from atlas_db import Element, Sheet

log = structlog.get_logger("atlas.api.reconstruct_translator")


# Keys we lift from Element.attrs into dedicated Pydantic model fields
# rather than into the catch-all ``properties`` dict.
_WALL_CONSUMED_ATTRS = {"thickness", "height", "is_exterior"}
_DOOR_CONSUMED_ATTRS = {"width", "height", "swing_angle_deg"}
_WINDOW_CONSUMED_ATTRS = {"width", "height", "sill_height"}
_ROOM_CONSUMED_ATTRS = {"area"}


@dataclass
class TranslatorStats:
    """Per-sheet accounting of where the extractor fell short.

    Surfaces in the API response so we can watch how often real
    drawings need default-patching and decide when to prioritise
    the proper extractor fix.
    """

    missing_door_width: int = 0
    missing_window_width: int = 0
    missing_wall_thickness: int = 0
    synthesized_insert_bbox: int = 0
    dropped_elements: int = 0
    dropped_reasons: dict[str, int] = field(default_factory=dict)

    def _dropped(self, reason: str) -> None:
        self.dropped_elements += 1
        self.dropped_reasons[reason] = self.dropped_reasons.get(reason, 0) + 1


def elements_to_structured_sheet(
    sheet_row: Sheet,
    element_rows: list[Element],
    *,
    default_door_width_m: float = 0.91,
    default_window_width_m: float = 1.22,
    default_wall_thickness_m: float = 0.15,
    default_insert_bbox_m: float = 0.5,
) -> tuple[StructuredSheet, TranslatorStats]:
    """Translate a sheet's ORM elements into a strict ``StructuredSheet``.

    Non-structural element kinds (columns, stairs, dimensions,
    annotations, symbols, other) are ignored — the 3D reconstructor
    only consumes walls, doors, windows, and rooms.

    Elements that can't be repaired even with defaults (malformed
    geometry, no centerline points on a wall, empty polygon on a
    room, etc.) are dropped and counted under
    :class:`TranslatorStats.dropped_reasons`.
    """

    stats = TranslatorStats()
    out_elements: list[Wall | Door | Window | Room] = []

    for row in element_rows:
        kind = row.kind
        try:
            if kind == ElementKind.WALL.value:
                model = _translate_wall(
                    row,
                    stats=stats,
                    default_wall_thickness_m=default_wall_thickness_m,
                )
            elif kind == ElementKind.DOOR.value:
                model = _translate_door(
                    row,
                    stats=stats,
                    default_door_width_m=default_door_width_m,
                    default_insert_bbox_m=default_insert_bbox_m,
                )
            elif kind == ElementKind.WINDOW.value:
                model = _translate_window(
                    row,
                    stats=stats,
                    default_window_width_m=default_window_width_m,
                    default_insert_bbox_m=default_insert_bbox_m,
                )
            elif kind == ElementKind.ROOM.value:
                model = _translate_room(row, stats=stats)
            else:
                # Non-structural kinds (column, stair, dimension, …)
                # aren't consumed by reconstruct3d — silently skip.
                continue
        except _Unsalvageable as exc:
            stats._dropped(exc.reason)
            log.info(
                "translator.dropped_element",
                element_id=str(row.id),
                kind=kind,
                reason=exc.reason,
            )
            continue

        if model is not None:
            out_elements.append(model)

    sheet = StructuredSheet(
        id=sheet_row.id,
        sheet_number=str(sheet_row.page_number),
        elements=out_elements,
    )
    return sheet, stats


# ---------------------------------------------------------------------------
# Kind-specific translators
# ---------------------------------------------------------------------------


class _Unsalvageable(Exception):
    """Sentinel for "this row can't be repaired; drop it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _translate_wall(
    row: Element,
    *,
    stats: TranslatorStats,
    default_wall_thickness_m: float,
) -> Wall:
    points = _polyline_points(row.geometry)
    if len(points) < 2:
        raise _Unsalvageable("wall_missing_centerline")

    attrs = row.attrs or {}
    thickness = attrs.get("thickness")
    if thickness is None:
        thickness = default_wall_thickness_m
        stats.missing_wall_thickness += 1
        log.info(
            "translator.default_applied",
            element_id=str(row.id),
            kind="wall",
            field="thickness",
            value=default_wall_thickness_m,
        )

    return Wall(
        id=row.id,
        centerline=Polyline(points=points),
        thickness=thickness,
        height=_opt_float(attrs.get("height")),
        is_exterior=_infer_is_exterior(row, attrs),
        **_common_element_fields(row, consumed=_WALL_CONSUMED_ATTRS),
    )


def _translate_door(
    row: Element,
    *,
    stats: TranslatorStats,
    default_door_width_m: float,
    default_insert_bbox_m: float,
) -> Door:
    attrs = row.attrs or {}
    width = _opt_float(attrs.get("width"))
    if width is None or width <= 0:
        width = default_door_width_m
        stats.missing_door_width += 1
        log.info(
            "translator.default_applied",
            element_id=str(row.id),
            kind="door",
            field="width",
            value=default_door_width_m,
        )

    bbox = _bbox_or_synthesize(
        row,
        stats=stats,
        default_insert_bbox_m=default_insert_bbox_m,
    )

    return Door(
        id=row.id,
        width=width,
        height=_opt_float(attrs.get("height")),
        swing_angle_deg=_opt_float(attrs.get("swing_angle_deg")),
        host_wall_id=row.host_element_id,
        bbox=bbox,
        **_common_element_fields(row, consumed=_DOOR_CONSUMED_ATTRS, override_bbox=True),
    )


def _translate_window(
    row: Element,
    *,
    stats: TranslatorStats,
    default_window_width_m: float,
    default_insert_bbox_m: float,
) -> Window:
    attrs = row.attrs or {}
    width = _opt_float(attrs.get("width"))
    if width is None or width <= 0:
        width = default_window_width_m
        stats.missing_window_width += 1
        log.info(
            "translator.default_applied",
            element_id=str(row.id),
            kind="window",
            field="width",
            value=default_window_width_m,
        )

    bbox = _bbox_or_synthesize(
        row,
        stats=stats,
        default_insert_bbox_m=default_insert_bbox_m,
    )

    return Window(
        id=row.id,
        width=width,
        height=_opt_float(attrs.get("height")),
        sill_height=_opt_float(attrs.get("sill_height")),
        host_wall_id=row.host_element_id,
        bbox=bbox,
        **_common_element_fields(row, consumed=_WINDOW_CONSUMED_ATTRS, override_bbox=True),
    )


def _translate_room(row: Element, *, stats: TranslatorStats) -> Room:
    ring, holes = _polygon_rings(row.geometry)
    if len(ring) < 3:
        raise _Unsalvageable("room_malformed")

    # Validate via shapely — catches self-intersections and zero-area.
    try:
        sp = sg.Polygon([(p.x, p.y) for p in ring], [[(p.x, p.y) for p in h] for h in holes])
        if not sp.is_valid or sp.area <= 0:
            raise _Unsalvageable("room_malformed")
    except _Unsalvageable:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise _Unsalvageable("room_malformed") from exc

    attrs = row.attrs or {}
    area = _opt_float(attrs.get("area"))
    if area is not None and area < 0:
        # Extractor shouldn't produce negative areas, but ``Room.area``
        # is ge=0 — fall through to None rather than explode.
        area = None
    return Room(
        id=row.id,
        boundary=Polygon(ring=ring, holes=holes),
        area=area,
        name=row.name,
        number=row.number,
        **_common_element_fields(row, consumed=_ROOM_CONSUMED_ATTRS, skip_name_number=True),
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _common_element_fields(
    row: Element,
    *,
    consumed: set[str],
    override_bbox: bool = False,
    skip_name_number: bool = False,
) -> dict[str, Any]:
    """Fields every element kind inherits from ``_ElementBase``.

    ``override_bbox=True`` tells the caller it's already supplying
    ``bbox`` (e.g. after synthesis), so we shouldn't also pass the
    raw ``row.bbox`` dict here.
    ``skip_name_number=True`` means the caller is passing
    ``name``/``number`` itself (Room does; others don't carry them).
    """
    out: dict[str, Any] = {
        "confidence": row.confidence,
        "source_layer": row.source_layer,
        "ncs_layer": row.ncs_layer,
        "ncs_major_group": row.ncs_major_group,
        "ncs_minor_group": row.ncs_minor_group,
        "ifc_type": row.ifc_type,
        "ifc_properties": row.ifc_properties or {},
        "properties": _scalar_properties(row.attrs or {}, consumed=consumed),
    }
    if not override_bbox:
        out["bbox"] = _bbox_from_dict(row.bbox)
    if not skip_name_number:
        # Wall/Door/Window don't carry name/number on the Pydantic side
        # — they inherit from _ElementBase which doesn't expose them.
        pass
    return out


def _scalar_properties(
    attrs: dict[str, Any], *, consumed: set[str]
) -> dict[str, str | int | float | bool | None]:
    """Return a scalar-only subset of ``attrs`` minus already-consumed keys.

    The ``_ElementBase.properties`` field is typed
    ``dict[str, str|int|float|bool|None]``, so nested dicts / lists
    would fail validation. Filter them out rather than raising.
    """
    out: dict[str, str | int | float | bool | None] = {}
    for k, v in attrs.items():
        if k in consumed:
            continue
        if isinstance(v, str | int | float | bool) or v is None:
            out[k] = v
    return out


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _infer_is_exterior(row: Element, attrs: dict[str, Any]) -> bool:
    """Exterior-ness hints, in preference order: attrs → NCS → source_layer."""
    explicit = attrs.get("is_exterior")
    if isinstance(explicit, bool):
        return explicit
    if row.ncs_minor_group == "EXTR":
        return True
    if row.source_layer and "EXTR" in row.source_layer.upper():
        return True
    return False


def _polyline_points(geometry: dict[str, Any] | None) -> list[Point]:
    if not geometry:
        return []
    if geometry.get("kind") != "polyline":
        return []
    raw = geometry.get("points") or []
    out: list[Point] = []
    for p in raw:
        try:
            out.append(Point(x=float(p["x"]), y=float(p["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _polygon_rings(
    geometry: dict[str, Any] | None,
) -> tuple[list[Point], list[list[Point]]]:
    if not geometry or geometry.get("kind") != "polygon":
        return [], []
    ring_raw = geometry.get("ring") or []
    ring: list[Point] = []
    for p in ring_raw:
        try:
            ring.append(Point(x=float(p["x"]), y=float(p["y"])))
        except (KeyError, TypeError, ValueError):
            continue

    holes_out: list[list[Point]] = []
    for h in geometry.get("holes") or []:
        h_pts: list[Point] = []
        for p in h:
            try:
                h_pts.append(Point(x=float(p["x"]), y=float(p["y"])))
            except (KeyError, TypeError, ValueError):
                continue
        if len(h_pts) >= 3:
            holes_out.append(h_pts)
    return ring, holes_out


def _bbox_from_dict(bb: dict[str, Any] | None) -> BoundingBox | None:
    if not bb:
        return None
    try:
        return BoundingBox(
            minx=float(bb["minx"]),
            miny=float(bb["miny"]),
            maxx=float(bb["maxx"]),
            maxy=float(bb["maxy"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _bbox_or_synthesize(
    row: Element,
    *,
    stats: TranslatorStats,
    default_insert_bbox_m: float,
) -> BoundingBox | None:
    """Prefer the extractor's bbox; otherwise centre a default box on the
    element's geometry anchor.

    The only real-world miss so far is INSERT-sourced doors and windows
    (ezdxf reports the insertion point but not the block's extents), so
    we fall back to a square of side ``default_insert_bbox_m`` centred
    on ``geometry.center``. That's lossy — the real shape is whatever
    the block contains — but it gives ``reconstruct3d`` a bbox centre
    to project onto the host wall's centerline, which is all it needs.
    """
    existing = _bbox_from_dict(row.bbox)
    if existing is not None:
        return existing

    geom = row.geometry or {}
    if geom.get("kind") != "insert":
        # No anchor point to centre on — leave None and let
        # reconstruct3d decide whether it can still place the element.
        return None
    center = geom.get("center") or {}
    try:
        cx = float(center["x"])
        cy = float(center["y"])
    except (KeyError, TypeError, ValueError):
        return None

    half = default_insert_bbox_m / 2.0
    stats.synthesized_insert_bbox += 1
    log.info(
        "translator.bbox_synthesized",
        element_id=str(row.id),
        kind=row.kind,
        center=[cx, cy],
        side_m=default_insert_bbox_m,
    )
    return BoundingBox(
        minx=cx - half, miny=cy - half, maxx=cx + half, maxy=cy + half
    )
