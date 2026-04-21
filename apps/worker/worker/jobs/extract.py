"""Element-extraction orchestrator.

Composes the Phase 2 reader + validators + Phase 3 DXF reader and
persists the result as ``Element`` rows under a new ``ElementSource``.
Phase 3 ships the function-shaped entrypoint; Phase 4 will wrap it
in an RQ job and wire it to the upload flow for non-PDF formats.

Lifecycle of a single run:

1. Insert ``ElementSource`` row with ``status=running``, publish
   ``extraction.started`` event.
2. Read the DXF — get a list of candidates plus a summary.
3. For each candidate, build the ``Element`` row attached to the
   chosen sheet + source. Periodically publish progress events so a
   future WS subscriber sees the stream as it lands.
4. On success, mark the source ``completed``, store the layer/skip
   summary in ``ElementSource.summary``, publish
   ``extraction.completed``. Return :class:`ExtractionRunSummary`.
5. On any exception, mark the source ``failed`` with the error
   code/message, publish ``extraction.failed``, and re-raise so the
   caller (or RQ) sees the original traceback.

Event payloads on Redis (channel ``atlas:drawing:{id}:events``):

    {"type": "extraction.started",   "drawing_id": ..., "source_id": ...}
    {"type": "extraction.progress",  "drawing_id": ..., "source_id": ...,
                                      "elements_so_far": N}
    {"type": "extraction.completed", "drawing_id": ..., "source_id": ...,
                                      "summary": {...}}
    {"type": "extraction.failed",    "drawing_id": ..., "source_id": ...,
                                      "error_code": ..., "error_message": ...}
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import structlog
from atlas_db import Element, ElementSource, Sheet
from sqlalchemy import select
from sqlalchemy.orm import Session

from worker import events
from worker.extractors import dxf

log = structlog.get_logger("atlas.worker.jobs.extract")

PRODUCER_NAME = "dxf_ncs_extractor"
PRODUCER_VERSION = "0.1.0"
PROGRESS_EVERY = 25  # publish a progress event every N elements


@dataclass(slots=True)
class ExtractionRunSummary:
    """Returned by :func:`extract_from_dxf` on success."""

    source_id: UUID
    elements_written: int
    elements_by_kind: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    layer_counts: dict[str, int] = field(default_factory=dict)
    skipped_entity_types: dict[str, int] = field(default_factory=dict)


def extract_from_dxf(
    session: Session,
    drawing_id: UUID,
    dxf_path: Path,
    *,
    source_id: UUID | None = None,
    sheet_id: UUID | None = None,
    producer_version: str = PRODUCER_VERSION,
) -> ExtractionRunSummary:
    """Run the DXF extractor against a drawing.

    The caller owns the SQLAlchemy session; we commit at meaningful
    boundaries so a partial run leaves a coherent ``ElementSource``
    in the DB even if the host process crashes.

    ``source_id`` selects between two modes:

    - **None (standalone path).** The orchestrator inserts a fresh
      ``ElementSource`` row in ``running`` state and runs to
      completion. Used by direct callers and the existing test
      fixtures.
    - **Provided (RQ path).** The API has already created the source
      in ``queued`` state and enqueued this job. The orchestrator
      transitions it to ``running`` and proceeds. The source row's
      ``params`` typically already records the DXF's S3 key + size.

    ``sheet_id`` selects which sheet to attach elements to. If None,
    the drawing's first (lowest ``page_number``) sheet is used —
    this matches the common case where a DXF represents one sheet.
    """
    started = time.monotonic()
    sheet_uuid = _resolve_sheet_id(session, drawing_id, sheet_id)

    if source_id is None:
        source = ElementSource(
            drawing_id=drawing_id,
            source_kind="extraction",
            producer_name=PRODUCER_NAME,
            producer_version=producer_version,
            status="running",
            started_at=datetime.now(UTC),
            params={"dxf_path": str(dxf_path)},
        )
        session.add(source)
        session.commit()
        session.refresh(source)
    else:
        source = session.get(ElementSource, source_id)
        if source is None:
            raise ValueError(f"ElementSource {source_id} not found")
        if source.drawing_id != drawing_id:
            raise ValueError(
                f"ElementSource {source_id} belongs to a different drawing"
            )
        source.status = "running"
        source.started_at = datetime.now(UTC)
        session.add(source)
        session.commit()
        session.refresh(source)

    events.publish(
        drawing_id,
        {
            "type": "extraction.started",
            "drawing_id": str(drawing_id),
            "source_id": str(source.id),
            "producer": f"{PRODUCER_NAME}@{producer_version}",
        },
    )
    log.info(
        "extract.started",
        drawing_id=str(drawing_id),
        source_id=str(source.id),
        dxf_path=str(dxf_path),
    )

    try:
        read_summary = dxf.read_dxf(dxf_path)
        kind_counts: dict[str, int] = {}
        elements_written = 0

        for candidate in read_summary.candidates:
            session.add(_candidate_to_element(candidate, sheet_uuid, source.id))
            kind_counts[candidate.kind.value] = kind_counts.get(candidate.kind.value, 0) + 1
            elements_written += 1

            if elements_written % PROGRESS_EVERY == 0:
                session.flush()
                events.publish(
                    drawing_id,
                    {
                        "type": "extraction.progress",
                        "drawing_id": str(drawing_id),
                        "source_id": str(source.id),
                        "elements_so_far": elements_written,
                    },
                )

        # Final flush + finalize.
        session.flush()

        # M3 Phase 2: post-extraction connectivity analysis. Populates
        # door host_element_id, inserts derived rooms (kind=room with
        # attrs.derived=true), records counts in the source summary.
        # Adjacency is computed on-demand by the API, not persisted.
        connectivity_summary = _run_connectivity_analysis(
            session, source.id, sheet_uuid
        )
        # The post-pass may have inserted derived rooms; reflect that
        # in the elements counters before finalizing.
        elements_written += connectivity_summary["derived_rooms"]
        kind_counts["room"] = (
            kind_counts.get("room", 0) + connectivity_summary["derived_rooms"]
        )

        source.status = "completed"
        source.finished_at = datetime.now(UTC)
        source.summary = {
            "elements_written": elements_written,
            "elements_by_kind": kind_counts,
            "layer_counts": read_summary.layer_counts,
            "skipped_entity_types": read_summary.skipped_entity_types,
            "skipped_unknown_layers": read_summary.skipped_unknown_layers,
            "connectivity": connectivity_summary,
        }
        session.add(source)
        session.commit()

        duration = round(time.monotonic() - started, 3)
        events.publish(
            drawing_id,
            {
                "type": "extraction.completed",
                "drawing_id": str(drawing_id),
                "source_id": str(source.id),
                "summary": source.summary,
                "duration_seconds": duration,
            },
        )
        log.info(
            "extract.completed",
            drawing_id=str(drawing_id),
            source_id=str(source.id),
            elements=elements_written,
            duration_seconds=duration,
        )

        return ExtractionRunSummary(
            source_id=source.id,
            elements_written=elements_written,
            elements_by_kind=kind_counts,
            duration_seconds=duration,
            layer_counts=read_summary.layer_counts,
            skipped_entity_types=read_summary.skipped_entity_types,
        )

    except Exception as exc:
        # Roll back any pending element inserts so the source row is
        # the only thing that lands; mark it failed in a fresh tx.
        session.rollback()
        source = session.get(ElementSource, source.id)
        if source is not None:
            source.status = "failed"
            source.error_code = type(exc).__name__
            source.error_message = str(exc)[:2048]
            source.finished_at = datetime.now(UTC)
            session.commit()
            events.publish(
                drawing_id,
                {
                    "type": "extraction.failed",
                    "drawing_id": str(drawing_id),
                    "source_id": str(source.id),
                    "error_code": source.error_code,
                    "error_message": source.error_message,
                },
            )
        log.exception(
            "extract.failed",
            drawing_id=str(drawing_id),
            source_id=str(source.id) if source else None,
        )
        raise


def _resolve_sheet_id(
    session: Session, drawing_id: UUID, sheet_id: UUID | None
) -> UUID:
    if sheet_id is not None:
        return sheet_id
    sheet = session.execute(
        select(Sheet)
        .where(Sheet.drawing_id == drawing_id)
        .order_by(Sheet.page_number.asc())
        .limit(1)
    ).scalar_one_or_none()
    if sheet is None:
        raise ValueError(
            f"Drawing {drawing_id} has no sheets; cannot attach elements"
        )
    return sheet.id


def _candidate_to_element(
    candidate: dxf.ElementCandidate,
    sheet_id: UUID,
    source_id: UUID,
) -> Element:
    return Element(
        sheet_id=sheet_id,
        source_id=source_id,
        kind=candidate.kind.value,
        confidence=candidate.confidence,
        source_layer=candidate.source_layer,
        ncs_layer=candidate.ncs_layer,
        ncs_major_group=candidate.ncs_major_group,
        ncs_minor_group=candidate.ncs_minor_group,
        ifc_type=candidate.ifc_type,
        ifc_properties=candidate.ifc_properties,
        geometry=candidate.geometry,
        bbox=candidate.bbox,
        attrs=candidate.attrs,
    )


def candidates_to_elements(
    candidates: Iterable[dxf.ElementCandidate],
    sheet_id: UUID,
    source_id: UUID,
) -> list[Element]:
    """Helper: bulk convert candidates → Element rows. Used by tests."""
    return [_candidate_to_element(c, sheet_id, source_id) for c in candidates]


# ---------- M3 Phase 2: connectivity post-pass ----------


def _run_connectivity_analysis(
    session: Session,
    source_id: UUID,
    sheet_id: UUID,
) -> dict[str, int]:
    """Compute opening hosting + derive rooms from wall loops.

    Operates on the elements just written by the orchestrator. Three
    side effects:

    1. ``Element.host_element_id`` set on every door and window whose
       centre sits on a wall (within tolerance). Doors and windows go
       through the same geometric path — a window's insertion point
       is indistinguishable from a door's arc centre to the hosting
       algorithm.
    2. New ``Element`` rows inserted for each derived room (CCW
       interior face of the wall planar graph), tagged
       ``attrs.derived = True`` so downstream code can distinguish
       them from explicitly-drawn A-ROOM polygons.
    3. Adjacency edges are *counted* into the returned summary so
       the source row records "this run produced N adjacencies",
       but the actual edges are computed on-demand by the API to
       avoid a new table.

    Pure side-effecting; doesn't commit.
    """
    from atlas_core import connectivity

    walls = (
        session.query(Element)
        .filter(Element.source_id == source_id, Element.kind == "wall")
        .all()
    )
    doors = (
        session.query(Element)
        .filter(Element.source_id == source_id, Element.kind == "door")
        .all()
    )
    windows = (
        session.query(Element)
        .filter(Element.source_id == source_id, Element.kind == "window")
        .all()
    )

    if not walls:
        return {
            "hosted_doors": 0,
            "hosted_windows": 0,
            "unhostable_openings": 0,
            "derived_rooms": 0,
            "adjacencies": 0,
        }

    # Marshal ORM rows into the algorithm's bare-tuple shapes. Walls
    # drawn as multi-vertex LWPOLYLINEs (L-shaped partitions, curved
    # exterior after SPLINE flattening) contribute one segment per
    # consecutive vertex pair; we keep a parallel parent list so
    # hosting can attribute a matched segment back to its Element row.
    # See G-R5 in docs/research/extractor-gaps.md.
    wall_segments: list[connectivity.Segment] = []
    segment_parent: list[Element] = []
    for wall in walls:
        for seg in _wall_segments(wall):
            wall_segments.append(seg)
            segment_parent.append(wall)

    hosted_doors, unhostable_doors = _host_openings(
        session, doors, wall_segments, segment_parent
    )
    hosted_windows, unhostable_windows = _host_openings(
        session, windows, wall_segments, segment_parent
    )
    unhostable_openings = unhostable_doors + unhostable_windows

    # Room adjacency needs door centres too. Skip any door whose
    # geometry didn't produce a computable centre — including it as
    # (0, 0) would poison the adjacency graph the same way it poisoned
    # hosting pre-fix.
    door_centers: list[connectivity.Point] = []
    for d in doors:
        c = _opening_center(d)
        if c is not None:
            door_centers.append(c)

    # Derive rooms from the wall planar graph; persist each as a new
    # Element row tagged derived=True — unless an explicit A-ROOM
    # polygon already covers the same footprint (G-O1), in which
    # case we annotate the explicit element instead of inserting a
    # duplicate.
    derived = connectivity.derive_rooms_from_walls(wall_segments)
    explicit_rooms = (
        session.query(Element)
        .filter(
            Element.source_id == source_id,
            Element.kind == "room",
            # Explicit rows have no derivation flag; derived rows set
            # attrs.derived=True. Filtering in Python is fine — a
            # single sheet has few rooms.
        )
        .all()
    )
    explicit_rooms = [
        r for r in explicit_rooms if not (r.attrs or {}).get("derived")
    ]
    explicit_polygons = [_explicit_polygon(r) for r in explicit_rooms]
    matches = connectivity.dedup_derived_against_explicit(derived, explicit_polygons)

    confirmed_explicit = 0
    inserted_derived = 0
    for i, room in enumerate(derived):
        match_idx = matches[i]
        if match_idx is not None:
            existing = explicit_rooms[match_idx]
            merged = dict(existing.attrs or {})
            merged["derivation_confirmed"] = True
            merged["derived_area"] = round(room.area, 6)
            existing.attrs = merged
            session.add(existing)
            confirmed_explicit += 1
            continue
        ring = [{"x": p[0], "y": p[1]} for p in room.ring]
        session.add(Element(
            sheet_id=sheet_id,
            source_id=source_id,
            kind="room",
            ifc_type="IfcSpace",
            geometry={"kind": "polygon", "ring": ring},
            bbox={
                "minx": room.bbox[0], "miny": room.bbox[1],
                "maxx": room.bbox[2], "maxy": room.bbox[3],
            },
            attrs={
                "derived": True,
                "derivation": "wall_loop",
                "area": round(room.area, 6),
            },
            confidence=0.85,
        ))
        inserted_derived += 1
    session.flush()

    # Count adjacency edges for the run summary; actual edges are
    # rebuilt on demand by the connectivity API.
    edges = connectivity.room_adjacency_via_doors(derived, door_centers)

    return {
        "hosted_doors": hosted_doors,
        "hosted_windows": hosted_windows,
        "unhostable_openings": unhostable_openings,
        "derived_rooms": inserted_derived,
        "confirmed_explicit_rooms": confirmed_explicit,
        "adjacencies": len(edges),
    }


def _host_openings(
    session: Session,
    openings: list[Element],
    wall_segments: list[tuple[tuple[float, float], tuple[float, float]]],
    segment_parent: list[Element],
) -> tuple[int, int]:
    """Write ``host_element_id`` on every opening that matches a wall.

    Same algorithm for doors and windows — the geometry doesn't know
    the difference. Openings whose geometry can't produce a centre
    (unknown ``kind``, missing vertices, malformed dict) are *not*
    hosted at all rather than hosted-to-origin — a silently-wrong
    result is worse than a visibly-unhosted one.

    Returns ``(hosted_count, unhostable_count)``. The sum of these two
    can be less than ``len(openings)``: openings with a valid centre
    but no wall within ``max_distance`` are neither hosted nor
    unhostable — they're legitimately free-floating.
    """
    from atlas_core import connectivity

    if not openings:
        return 0, 0

    # Build centres once; None means "can't compute one" — skip this
    # opening's hosting entirely.
    valid_openings: list[Element] = []
    valid_centers: list[tuple[float, float]] = []
    unhostable = 0
    for o in openings:
        c = _opening_center(o)
        if c is None:
            unhostable += 1
            log.warning(
                "extract.unhostable_opening",
                element_id=str(o.id),
                kind=o.kind,
                geometry_kind=(o.geometry or {}).get("kind"),
            )
            continue
        valid_openings.append(o)
        valid_centers.append(c)

    hostings = connectivity.host_walls_for_openings(valid_centers, wall_segments)
    hosted = 0
    for h in hostings:
        if h.wall_index is None:
            continue
        valid_openings[h.opening_index].host_element_id = (
            segment_parent[h.wall_index].id
        )
        session.add(valid_openings[h.opening_index])
        hosted += 1
    return hosted, unhostable


def _wall_segments(
    wall: Element,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Expand a wall's polyline geometry into consecutive-vertex segments.

    A LINE wall has two points and yields one segment. A multi-vertex
    LWPOLYLINE wall (L-shaped partition, flattened SPLINE) yields N-1
    segments. Each caller pairs the returned segments with the same
    parent Element so hosting can attribute the match back.

    Degenerate geometry (missing points or only one vertex) returns
    an empty list — the caller simply skips the wall.
    """
    geom = wall.geometry or {}
    pts = geom.get("points") or []
    if len(pts) < 2:
        return []
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        segments.append((
            (float(a["x"]), float(a["y"])),
            (float(b["x"]), float(b["y"])),
        ))
    return segments


def _explicit_polygon(room: Element) -> tuple[
    list[tuple[float, float]], tuple[float, float, float, float]
]:
    """Ring + bbox tuple for an explicit A-ROOM element.

    Returns ``(ring, bbox)`` where ring is a list of (x, y) tuples
    and bbox is (minx, miny, maxx, maxy). Matches the shape the
    connectivity module uses for derived rooms.
    """
    geom = room.geometry or {}
    ring_raw = geom.get("ring") or []
    ring = [(float(p["x"]), float(p["y"])) for p in ring_raw]
    if ring:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        bbox = (min(xs), min(ys), max(xs), max(ys))
    else:
        bbox = (0.0, 0.0, 0.0, 0.0)
    return ring, bbox


def _opening_center(opening: Element) -> tuple[float, float] | None:
    """Compute the geometric centre of a door/window, dispatching by kind.

    Returns ``None`` when the geometry can't produce a meaningful
    centre — explicitly chosen over the pre-fix ``(0, 0)`` fallback,
    which silently misreported the centre of every centreless opening
    as world origin. An opening near origin + a wall passing through
    origin would then be falsely hosted on that wall. ``None`` makes
    the caller skip hosting entirely, which is loud (shows up in the
    ``unhostable_openings`` stat) rather than silently wrong.

    Kind dispatch:

    - ``insert`` / ``arc`` / ``circle`` → ``geometry.center`` (the
      insertion point / arc centre / circle centre).
    - ``polyline`` → mean of ``geometry.points``. For the common
      2-point window-as-sill-line case this is the midpoint; for
      multi-vertex polylines it's the centroid of the vertex
      polygon, which is good enough for proximity matching.
    - ``polygon`` → mean of ``geometry.ring``. Approximation of the
      true area-weighted centroid; fine for an opening's host-
      proximity check because openings are usually small.
    - ``raw`` / unknown / missing → ``None``.
    """
    geom = opening.geometry or {}
    kind = geom.get("kind")

    if kind in ("insert", "arc", "circle"):
        c = geom.get("center")
        if not c or "x" not in c or "y" not in c:
            return None
        try:
            return (float(c["x"]), float(c["y"]))
        except (TypeError, ValueError):
            return None

    if kind == "polyline":
        return _mean_point(geom.get("points") or [])

    if kind == "polygon":
        return _mean_point(geom.get("ring") or [])

    # ``raw``, ``None``, or any future unrecognised kind.
    return None


def _mean_point(pts: list[dict]) -> tuple[float, float] | None:
    """Arithmetic mean of an ``[{"x":, "y":}, ...]`` list.

    Returns None on an empty list or unparseable entries — the
    caller treats that as "no usable centre".
    """
    if not pts:
        return None
    sx = 0.0
    sy = 0.0
    n = 0
    for p in pts:
        try:
            sx += float(p["x"])
            sy += float(p["y"])
            n += 1
        except (KeyError, TypeError, ValueError):
            continue
    if n == 0:
        return None
    return (sx / n, sy / n)


# ---------- RQ entrypoint ----------


def run_dxf_extraction(source_id_str: str) -> None:
    """RQ entrypoint: download the queued DXF from S3 and run the orchestrator.

    The API is responsible for:

    1. Uploading the DXF to S3 under
       ``drawings/{drawing_id}/extractions/{source_id}/source.dxf``.
    2. Inserting an ``ElementSource`` row in ``queued`` state with
       ``params = {"dxf_s3_key": "...", "dxf_size_bytes": ...}``.
    3. Enqueuing this job with the source_id as a string (RQ
       serializes args via pickle but UUID-typed args have hit
       compatibility quirks across versions; strings are safer).

    On any error before extraction begins (S3 download fails, source
    row missing) we mark the source ``failed`` and emit
    ``extraction.failed`` so listeners aren't left hanging. Errors
    *during* extraction are handled by ``extract_from_dxf``.
    """
    # Local imports avoid a cycle when extract.py is imported at
    # worker module load (s3.py already pulls config which pulls env).
    import tempfile

    from worker import s3 as s3_mod
    from worker.config import get_settings
    from worker.db import session_scope

    source_id = UUID(source_id_str)
    log.info("extract.rq.start", source_id=source_id_str)

    with session_scope() as session:
        source = session.get(ElementSource, source_id)
        if source is None:
            raise RuntimeError(f"ElementSource {source_id} not found")

        drawing_id = source.drawing_id
        params = dict(source.params or {})
        dxf_s3_key = params.get("dxf_s3_key")
        if not dxf_s3_key:
            _fail_source(
                session,
                source,
                drawing_id,
                code="missing_s3_key",
                message="ElementSource.params.dxf_s3_key is missing",
            )
            raise RuntimeError(f"ElementSource {source_id} has no dxf_s3_key")

        with tempfile.TemporaryDirectory(prefix="atlas-extract-") as workdir:
            local_path = Path(workdir) / "source.dxf"
            try:
                s3_mod.get_s3_client().download_file(
                    get_settings().s3_bucket,
                    dxf_s3_key,
                    str(local_path),
                )
            except Exception as exc:
                _fail_source(
                    session,
                    source,
                    drawing_id,
                    code="s3_download_failed",
                    message=str(exc),
                )
                raise

            # Hand off to the existing orchestrator which transitions
            # queued → running and handles its own failure mode.
            extract_from_dxf(
                session,
                drawing_id,
                local_path,
                source_id=source_id,
            )


def _fail_source(
    session: Session,
    source: ElementSource,
    drawing_id: UUID,
    *,
    code: str,
    message: str,
) -> None:
    """Mark a source failed before the orchestrator runs (e.g. S3 missing).

    Mirrors the orchestrator's failure path so the API/WS see the
    same event shape regardless of where in the pipeline it died.
    """
    source.status = "failed"
    source.error_code = code
    source.error_message = message[:2048]
    source.finished_at = datetime.now(UTC)
    session.add(source)
    session.commit()
    events.publish(
        drawing_id,
        {
            "type": "extraction.failed",
            "drawing_id": str(drawing_id),
            "source_id": str(source.id),
            "error_code": code,
            "error_message": source.error_message,
        },
    )
    log.error(
        "extract.rq.failed_pre_orchestrator",
        source_id=str(source.id),
        code=code,
        message=message,
    )
