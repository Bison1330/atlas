"""Room connectivity endpoint.

GET /drawings/{id}/connectivity returns the room/door/adjacency graph
for a given extraction run (defaults to the latest completed). Rooms
include both *extracted* (from explicit A-ROOM polygons) and *derived*
(from the wall-loop post-pass) variants — the response carries a
``derived`` flag so a UI can distinguish.

Adjacencies aren't persisted; we recompute them on demand from the
elements + the connectivity geometry helpers. Two reasons:

1. No new schema or migration needed — the M3 Phase 2 work stays
   inside the existing tables.
2. Future re-extractions can change the graph; recomputing keeps the
   graph in sync with whatever the current source says without a
   stale-cache invalidation problem.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.db import Element, ElementSource, Sheet

router = APIRouter(prefix="/drawings", tags=["connectivity"])


class RoomNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    derived: bool
    name: str | None = None
    number: str | None = None
    area: float | None = None
    bbox: dict[str, float] | None = None
    ring: list[dict[str, float]] | None = None


class DoorNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    host_element_id: UUID | None = None
    center: dict[str, float] | None = None
    swing_angle_deg: float | None = None


class AdjacencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_a_id: UUID
    room_b_id: UUID
    door_id: UUID


class ConnectivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID
    source_id: UUID | None
    rooms: list[RoomNode] = Field(default_factory=list)
    doors: list[DoorNode] = Field(default_factory=list)
    adjacencies: list[AdjacencyEdge] = Field(default_factory=list)


@router.get(
    "/{drawing_id}/connectivity",
    response_model=ConnectivityResponse,
    summary="Room / door / adjacency graph for an extraction run",
)
def get_connectivity(
    drawing_id: UUID,
    source_id: Annotated[
        UUID | None,
        Query(description="Specific extraction run; defaults to latest completed."),
    ] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ConnectivityResponse:
    resolved = source_id or _latest_completed_source_id(db, drawing_id)
    if resolved is None:
        return ConnectivityResponse(drawing_id=drawing_id, source_id=None)

    rooms = list(db.execute(
        select(Element)
        .join(Sheet, Element.sheet_id == Sheet.id)
        .where(Sheet.drawing_id == drawing_id, Element.source_id == resolved,
               Element.kind == "room")
    ).scalars().all())

    doors = list(db.execute(
        select(Element)
        .join(Sheet, Element.sheet_id == Sheet.id)
        .where(Sheet.drawing_id == drawing_id, Element.source_id == resolved,
               Element.kind == "door")
    ).scalars().all())

    return ConnectivityResponse(
        drawing_id=drawing_id,
        source_id=resolved,
        rooms=[_room_node(r) for r in rooms],
        doors=[_door_node(d) for d in doors],
        adjacencies=_compute_adjacencies(rooms, doors),
    )


def _latest_completed_source_id(db: Session, drawing_id: UUID) -> UUID | None:
    return db.execute(
        select(ElementSource.id)
        .where(
            ElementSource.drawing_id == drawing_id,
            ElementSource.status == "completed",
        )
        .order_by(ElementSource.finished_at.desc().nullslast())
        .limit(1)
    ).scalar_one_or_none()


def _room_node(room: Element) -> RoomNode:
    geom = room.geometry or {}
    ring = geom.get("ring") if geom.get("kind") == "polygon" else None
    return RoomNode(
        id=room.id,
        derived=bool((room.attrs or {}).get("derived")),
        name=room.name,
        number=room.number,
        area=(room.attrs or {}).get("area"),
        bbox=room.bbox,
        ring=ring,
    )


def _door_node(door: Element) -> DoorNode:
    geom = door.geometry or {}
    center = geom.get("center") if geom.get("kind") == "arc" else None
    swing = (door.attrs or {}).get("swing_angle_deg") if door.attrs else None
    return DoorNode(
        id=door.id,
        host_element_id=door.host_element_id,
        center=center,
        swing_angle_deg=swing,
    )


def _compute_adjacencies(
    rooms: list[Element], doors: list[Element]
) -> list[AdjacencyEdge]:
    """Recompute room↔room edges from doors that touch room boundaries.

    Lightweight inline use of ``worker.extractors.connectivity`` —
    the API depends on the worker package via the shared import path,
    which is fine here because both run in the same monorepo. If we
    later split the worker into a separately-deployed service we'd
    extract this helper into atlas-core.
    """
    from atlas_core.connectivity import (
        DerivedRoom,
        room_adjacency_via_doors,
    )

    derived_rooms: list[DerivedRoom] = []
    room_index_to_id: dict[int, UUID] = {}
    for r in rooms:
        geom = r.geometry or {}
        if geom.get("kind") != "polygon":
            continue
        ring = [(p["x"], p["y"]) for p in geom.get("ring") or []]
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        # area is best-effort; the algorithm only uses ring + bbox here.
        area = (r.attrs or {}).get("area") or 0.0
        derived_rooms.append(DerivedRoom(
            ring=ring,
            area=float(area),
            bbox=(min(xs), min(ys), max(xs), max(ys)),
        ))
        room_index_to_id[len(derived_rooms) - 1] = r.id

    door_centers: list[tuple[float, float]] = []
    door_index_to_id: dict[int, UUID] = {}
    for d in doors:
        geom = d.geometry or {}
        c = geom.get("center")
        if not c:
            continue
        door_centers.append((float(c["x"]), float(c["y"])))
        door_index_to_id[len(door_centers) - 1] = d.id

    edges = room_adjacency_via_doors(derived_rooms, door_centers)
    return [
        AdjacencyEdge(
            room_a_id=room_index_to_id[e.room_a_index],
            room_b_id=room_index_to_id[e.room_b_index],
            door_id=door_index_to_id[e.door_index],
        )
        for e in edges
    ]


