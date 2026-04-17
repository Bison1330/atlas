"""Natural-language Q&A over extracted drawing elements (M5).

Shape of a query in this service:

1. **Interpret** the question into a structured
   :class:`QueryInterpretation` — one of the 5 supported buckets
   (count, quantity, rank, adjacency, lookup) plus a filter dict.
   This is the only LLM-touching step and happens via a pluggable
   :class:`Interpreter` protocol; tests pass in a fake interpreter,
   the real one calls Claude via tool use.

2. **Execute** the interpretation against the pre-fetched element
   list. Pure code — no LLM, no DB. Returns an :class:`AnswerData`
   whose citations are the ground truth for the formatted prose.

3. **Format** deterministic answer prose from the AnswerData. Prose
   is a function of the structured answer, not of the LLM — so the
   eval can regex-match with confidence.

The citation contract (per `docs/research/m5-design-intent-qa.md`)
is: *citations drive the answer, not the other way around*. Every
claim in the prose string maps to elements in ``citations``; if the
citation set is empty the answer cannot claim anything numeric.

Why "pre-fetched element list" (not a session): the route owns the
DB fetch so the service is trivially testable and the eval harness
can inject synthetic element lists without spinning up Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from atlas_core import connectivity as conn

AnswerBucket = Literal[
    "count", "quantity", "rank", "adjacency", "lookup", "unsupported"
]
AnswerCertainty = Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# Core data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryInterpretation:
    """Structured parse of a natural-language question.

    ``unsupported_reason`` is populated when the interpreter decided
    the question falls outside the 5 supported buckets; the
    executor returns a 400-style payload in that case instead of
    a fabricated answer.
    """

    bucket: AnswerBucket
    filter: dict[str, Any] = field(default_factory=dict)
    unsupported_reason: str | None = None
    suggested_phrasing: str | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    element_id: UUID
    sheet_id: UUID
    kind: str
    ncs_layer: str | None
    bbox: dict[str, float] | None
    display_label: str


@dataclass(frozen=True, slots=True)
class AnswerData:
    """Executor output: the facts + citations that drive the prose.

    ``value`` is bucket-specific: an int for count, a float + unit
    for quantity, a single dict for rank/lookup, a bool + optional
    via-door for adjacency.
    """

    value: Any
    unit: str | None
    citations: list[Citation]
    answer_certainty: AnswerCertainty
    extraction_min: float | None


@dataclass(frozen=True, slots=True)
class AnswerPayload:
    """Route-facing response shape (pre-Pydantic serialization)."""

    answer: str
    answer_type: AnswerBucket
    citations: list[Citation]
    interpretation: QueryInterpretation
    extraction_min: float | None
    answer_certainty: AnswerCertainty


# Sentinel returned by executors when the interpretation can't be
# matched to any element. Callers treat this as a 0-result answer.
_EMPTY_ANSWER = AnswerData(
    value=None, unit=None, citations=[],
    answer_certainty="low", extraction_min=None,
)


# ---------------------------------------------------------------------------
# Interpreter protocol
# ---------------------------------------------------------------------------


class Interpreter(Protocol):
    """Turn a natural-language question into a QueryInterpretation.

    Implementations:

    - :class:`ClaudeInterpreter` (real) — calls the Anthropic API
      with tool use so output is strictly-typed JSON.
    - ``FakeInterpreter`` (tests) — returns a pre-baked mapping of
      question → QueryInterpretation.
    """

    def interpret(
        self, question: str, drawing_context: dict[str, Any]
    ) -> QueryInterpretation: ...


# ---------------------------------------------------------------------------
# Element adapter — duck-typed so eval harness can pass plain dicts
# ---------------------------------------------------------------------------


def _attr(element: Any, name: str, default: Any = None) -> Any:
    """Duck-typed attribute read.

    The service consumes both SQLAlchemy ``Element`` rows (production)
    and plain dicts/dataclasses (eval harness, unit tests). ``_attr``
    reads either without the caller branching.
    """
    if isinstance(element, dict):
        return element.get(name, default)
    return getattr(element, name, default)


def _geom(element: Any) -> dict[str, Any]:
    return _attr(element, "geometry") or {}


def _attrs_map(element: Any) -> dict[str, Any]:
    return _attr(element, "attrs") or {}


def _bbox(element: Any) -> dict[str, float] | None:
    b = _attr(element, "bbox")
    if b is None:
        return None
    if isinstance(b, dict):
        return b
    return None


def _confidence(element: Any) -> float | None:
    c = _attr(element, "confidence")
    return float(c) if c is not None else None


# ---------------------------------------------------------------------------
# Room indexing — one-based, ordered by descending area
# ---------------------------------------------------------------------------


def _room_area(room: Any) -> float:
    """Area preference: explicit attrs.area → derived_area → polygon shoelace."""
    attrs = _attrs_map(room)
    for key in ("area", "derived_area"):
        v = attrs.get(key)
        if v is not None:
            return float(v)
    ring = _geom(room).get("ring") or []
    if len(ring) < 3:
        return 0.0
    pts = [(float(p["x"]), float(p["y"])) for p in ring]
    return abs(conn._signed_area(pts))  # type: ignore[attr-defined]


def _sorted_rooms(rooms: list[Any]) -> list[Any]:
    """Area-desc so ``room 1`` is largest, matching the M3 convention."""
    return sorted(rooms, key=_room_area, reverse=True)


def _resolve_room(
    rooms_sorted: list[Any], identifier: str | int | UUID
) -> Any | None:
    """Resolve a room identifier to an element.

    Accepts:
    - an ``int`` or ``str`` like ``"1"`` / ``"room 1"`` — 1-based
      index into ``rooms_sorted``;
    - a UUID — exact match on ``element.id``.
    """
    if isinstance(identifier, UUID):
        for r in rooms_sorted:
            if _attr(r, "id") == identifier:
                return r
        return None
    if isinstance(identifier, int):
        idx = identifier - 1
        return rooms_sorted[idx] if 0 <= idx < len(rooms_sorted) else None
    if isinstance(identifier, str):
        s = identifier.strip().lower()
        if s.startswith("room"):
            s = s.replace("room", "").strip()
        s = s.strip("#").strip()
        if s.isdigit():
            return _resolve_room(rooms_sorted, int(s))
        # attrs.name / attrs.number match — if the authoring tool
        # attached one to the A-ROOM polygon.
        for r in rooms_sorted:
            a = _attrs_map(r)
            if (
                (a.get("name") or "").lower() == identifier.lower()
                or (a.get("number") or "").lower() == identifier.lower()
            ):
                return r
    return None


# ---------------------------------------------------------------------------
# Citation construction
# ---------------------------------------------------------------------------


def _citation(element: Any) -> Citation:
    kind = _attr(element, "kind") or "unknown"
    bb = _bbox(element)
    label = _display_label(element, kind, bb)
    return Citation(
        element_id=UUID(str(_attr(element, "id"))),
        sheet_id=UUID(str(_attr(element, "sheet_id"))),
        kind=kind,
        ncs_layer=_attr(element, "ncs_layer"),
        bbox=bb,
        display_label=label,
    )


def _display_label(
    element: Any, kind: str, bb: dict[str, float] | None
) -> str:
    """Short human-readable pointer — good enough for a chat chip."""
    attrs = _attrs_map(element)
    if attrs.get("name"):
        return str(attrs["name"])
    if attrs.get("number"):
        return f"{kind.capitalize()} {attrs['number']}"
    if bb:
        cx = (bb["minx"] + bb["maxx"]) / 2
        cy = (bb["miny"] + bb["maxy"]) / 2
        return f"{kind.capitalize()} at ({cx:.1f}, {cy:.1f})"
    return f"{kind.capitalize()} {str(_attr(element, 'id'))[:8]}"


def _extraction_min(elements: list[Any]) -> float | None:
    vals = [_confidence(e) for e in elements if _confidence(e) is not None]
    return min(vals) if vals else None


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


def _matches_filter(element: Any, flt: dict[str, Any]) -> bool:
    for key in ("kind", "ncs_major_group", "ncs_minor_group"):
        want = flt.get(key)
        if want is None:
            continue
        have = _attr(element, key)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


# ---------------------------------------------------------------------------
# Geometry helpers (polyline_length, polygon_area — reused from takeoffs)
# ---------------------------------------------------------------------------


def _polyline_length(points: list[dict[str, Any]]) -> float:
    total = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        total += ((float(b["x"]) - float(a["x"])) ** 2
                  + (float(b["y"]) - float(a["y"])) ** 2) ** 0.5
    return total


def _polygon_area(ring: list[dict[str, Any]]) -> float:
    if len(ring) < 3:
        return 0.0
    pts = [(float(p["x"]), float(p["y"])) for p in ring]
    return abs(conn._signed_area(pts))  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Bucket executors
# ---------------------------------------------------------------------------


def _execute_count(
    interpretation: QueryInterpretation, elements: list[Any]
) -> AnswerData:
    matched = [e for e in elements if _matches_filter(e, interpretation.filter)]
    return AnswerData(
        value=len(matched),
        unit=None,
        citations=[_citation(e) for e in matched],
        answer_certainty="high" if matched else "medium",
        extraction_min=_extraction_min(matched),
    )


def _execute_quantity(
    interpretation: QueryInterpretation, elements: list[Any]
) -> AnswerData:
    flt = interpretation.filter
    metric = flt.get("metric")
    matched = [e for e in elements if _matches_filter(e, flt)]
    if not matched:
        return _EMPTY_ANSWER
    if metric == "length":
        total = sum(
            _polyline_length(_geom(e).get("points") or []) for e in matched
        )
        unit = "drawing units"
    elif metric == "area":
        total = sum(
            _polygon_area(_geom(e).get("ring") or []) for e in matched
        )
        unit = "square drawing units"
    else:
        return _EMPTY_ANSWER
    return AnswerData(
        value=round(total, 3),
        unit=unit,
        citations=[_citation(e) for e in matched],
        answer_certainty="high",
        extraction_min=_extraction_min(matched),
    )


def _execute_rank(
    interpretation: QueryInterpretation, elements: list[Any]
) -> AnswerData:
    flt = interpretation.filter
    direction = flt.get("direction", "max")
    matched = [e for e in elements if _matches_filter(e, flt)]
    if not matched:
        return _EMPTY_ANSWER

    metric = flt.get("metric")
    if metric == "area":
        scored = [(e, _polygon_area(_geom(e).get("ring") or [])) for e in matched]
    elif metric == "length":
        scored = [(e, _polyline_length(_geom(e).get("points") or [])) for e in matched]
    else:
        return _EMPTY_ANSWER

    scored.sort(key=lambda pair: pair[1], reverse=(direction == "max"))
    best, best_value = scored[0]
    unit = "square drawing units" if metric == "area" else "drawing units"
    return AnswerData(
        value={"element": _citation(best), "metric": metric, "measurement": round(best_value, 3)},
        unit=unit,
        citations=[_citation(best)],
        answer_certainty="high" if len(scored) == 1
            or abs(scored[0][1] - scored[1][1]) > 0.01 * best_value
            else "medium",
        extraction_min=_extraction_min([best]),
    )


def _execute_adjacency(
    interpretation: QueryInterpretation, elements: list[Any]
) -> AnswerData:
    """Room-to-room adjacency via hosted doors (M3).

    Supported sub-queries (via ``filter.query_type``):
    - ``rooms_connected``: are ``room_a`` and ``room_b`` connected? →
      bool + the bridging door as citation.
    - ``room_neighbors``: which rooms border ``room_a``? → list of
      neighbor room citations.
    """
    flt = interpretation.filter
    query_type = flt.get("query_type", "rooms_connected")

    rooms = _sorted_rooms([e for e in elements if _attr(e, "kind") == "room"])
    doors = [e for e in elements if _attr(e, "kind") == "door"]

    if not rooms:
        return _EMPTY_ANSWER

    # Map rooms to DerivedRoom-like tuples for the connectivity helper.
    room_shapes: list[conn.DerivedRoom] = []
    for r in rooms:
        ring_raw = _geom(r).get("ring") or []
        ring = [(float(p["x"]), float(p["y"])) for p in ring_raw]
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        room_shapes.append(conn.DerivedRoom(
            ring=ring,
            area=_room_area(r),
            bbox=(min(xs), min(ys), max(xs), max(ys)),
        ))

    door_centers: list[conn.Point] = []
    door_index_to_element: list[Any] = []
    for d in doors:
        c = _geom(d).get("center")
        if not c:
            continue
        door_centers.append((float(c["x"]), float(c["y"])))
        door_index_to_element.append(d)

    edges = conn.room_adjacency_via_doors(room_shapes, door_centers)

    if query_type == "rooms_connected":
        a = _resolve_room(rooms, flt.get("room_a"))
        b = _resolve_room(rooms, flt.get("room_b"))
        if a is None or b is None:
            return _EMPTY_ANSWER
        a_idx = rooms.index(a)
        b_idx = rooms.index(b)
        for edge in edges:
            if {edge.room_a_index, edge.room_b_index} == {a_idx, b_idx}:
                via_door = door_index_to_element[edge.door_index]
                return AnswerData(
                    value={"connected": True, "via_door_id": _attr(via_door, "id")},
                    unit=None,
                    citations=[_citation(a), _citation(b), _citation(via_door)],
                    answer_certainty="high",
                    extraction_min=_extraction_min([a, b, via_door]),
                )
        return AnswerData(
            value={"connected": False, "via_door_id": None},
            unit=None,
            citations=[_citation(a), _citation(b)],
            answer_certainty="high",
            extraction_min=_extraction_min([a, b]),
        )

    if query_type == "room_neighbors":
        target = _resolve_room(rooms, flt.get("room_a"))
        if target is None:
            return _EMPTY_ANSWER
        t_idx = rooms.index(target)
        neighbor_indices: set[int] = set()
        via_doors: list[Any] = []
        for edge in edges:
            if edge.room_a_index == t_idx:
                neighbor_indices.add(edge.room_b_index)
                via_doors.append(door_index_to_element[edge.door_index])
            elif edge.room_b_index == t_idx:
                neighbor_indices.add(edge.room_a_index)
                via_doors.append(door_index_to_element[edge.door_index])
        neighbors = [rooms[i] for i in sorted(neighbor_indices)]
        cites = [_citation(target)] + [_citation(n) for n in neighbors] \
            + [_citation(d) for d in via_doors]
        return AnswerData(
            value={"neighbors": [_citation(n) for n in neighbors]},
            unit=None,
            citations=cites,
            answer_certainty="high" if neighbors else "medium",
            extraction_min=_extraction_min([target, *neighbors]),
        )

    return _EMPTY_ANSWER


def _execute_lookup(
    interpretation: QueryInterpretation, elements: list[Any]
) -> AnswerData:
    """Specific attribute of a specific element (usually a room).

    ``filter`` shape: ``{"kind": "room", "identifier": "room 1",
    "attribute": "area"}``. Only ``kind=room`` + ``attribute=area``
    is wired in v1; extensions (door swing, wall length) land when
    real fixtures demand them.
    """
    flt = interpretation.filter
    kind = flt.get("kind") or "room"
    attribute = flt.get("attribute") or "area"

    if kind != "room":
        return _EMPTY_ANSWER

    rooms = _sorted_rooms([e for e in elements if _attr(e, "kind") == "room"])
    target = _resolve_room(rooms, flt.get("identifier"))
    if target is None:
        return _EMPTY_ANSWER

    if attribute == "area":
        area = _room_area(target)
        return AnswerData(
            value={"element": _citation(target), "attribute": "area", "measurement": round(area, 3)},
            unit="square drawing units",
            citations=[_citation(target)],
            answer_certainty="high",
            extraction_min=_extraction_min([target]),
        )

    return _EMPTY_ANSWER


_EXECUTORS = {
    "count": _execute_count,
    "quantity": _execute_quantity,
    "rank": _execute_rank,
    "adjacency": _execute_adjacency,
    "lookup": _execute_lookup,
}


# ---------------------------------------------------------------------------
# Deterministic prose formatting
# ---------------------------------------------------------------------------


def _format_count(data: AnswerData, flt: dict[str, Any]) -> str:
    n = int(data.value or 0)
    kind = flt.get("kind", "element")
    minor = flt.get("ncs_minor_group")
    noun = _pluralize(kind, n)
    qualifier = f" {minor.lower()}" if isinstance(minor, str) else ""
    return f"Found {n}{qualifier} {noun} (extracted)."


def _format_quantity(data: AnswerData, flt: dict[str, Any]) -> str:
    if data.value is None:
        return "No matching elements found."
    kind = flt.get("kind", "element")
    metric = flt.get("metric", "measurement")
    value = data.value
    unit = data.unit or ""
    return (
        f"Total {metric} of {_pluralize(kind, 2)}: {value} {unit} "
        f"(across {len(data.citations)} elements)."
    )


def _format_rank(data: AnswerData, flt: dict[str, Any]) -> str:
    if data.value is None:
        return "No matching elements found."
    direction = flt.get("direction", "max")
    superlative = "largest" if direction == "max" else "smallest"
    payload = data.value
    label = payload["element"].display_label
    unit = data.unit or ""
    return (
        f"The {superlative} {flt.get('kind', 'element')} is "
        f"{label} at {payload['measurement']} {unit}."
    )


def _format_adjacency(data: AnswerData, flt: dict[str, Any]) -> str:
    if data.value is None:
        return "Could not evaluate adjacency — rooms not found."
    qt = flt.get("query_type", "rooms_connected")
    if qt == "rooms_connected":
        if data.value.get("connected"):
            return (
                "Yes — the two rooms are connected via a door "
                f"({len(data.citations)} elements cited)."
            )
        return "No — those rooms are not directly connected by a door."
    if qt == "room_neighbors":
        neighbors = data.value.get("neighbors") or []
        if not neighbors:
            return "This room has no door-connected neighbors."
        labels = ", ".join(n.display_label for n in neighbors)
        return f"This room is connected to: {labels}."
    return "Unsupported adjacency query."


def _format_lookup(data: AnswerData, flt: dict[str, Any]) -> str:
    if data.value is None:
        return "Could not resolve the requested element."
    payload = data.value
    return (
        f"{payload['element'].display_label} — "
        f"{payload['attribute']}: {payload['measurement']} {data.unit or ''}"
    ).strip()


def _format_unsupported(interpretation: QueryInterpretation) -> str:
    reason = interpretation.unsupported_reason or "outside supported query types"
    suffix = (
        f" Try rephrasing: {interpretation.suggested_phrasing!r}."
        if interpretation.suggested_phrasing
        else ""
    )
    return f"I can't answer that yet — {reason}.{suffix}"


def _pluralize(kind: str, n: int) -> str:
    # Simple rule is enough for our small vocabulary.
    if n == 1:
        return kind
    if kind.endswith("s"):
        return kind
    return kind + "s"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def ask(
    question: str,
    elements: list[Any],
    interpreter: Interpreter,
    *,
    drawing_context: dict[str, Any] | None = None,
) -> AnswerPayload:
    """Run the full interpret → execute → format pipeline.

    ``elements`` is the pre-fetched list of Element rows (or dicts
    in tests / eval). ``drawing_context`` is any metadata the
    interpreter should know about — currently passed through to the
    LLM prompt (e.g. available element kinds, room count) so it can
    refuse out-of-scope questions early.
    """
    ctx = drawing_context or _default_context(elements)
    interpretation = interpreter.interpret(question, ctx)

    if interpretation.bucket == "unsupported":
        return AnswerPayload(
            answer=_format_unsupported(interpretation),
            answer_type="unsupported",
            citations=[],
            interpretation=interpretation,
            extraction_min=None,
            answer_certainty="low",
        )

    executor = _EXECUTORS.get(interpretation.bucket)
    if executor is None:  # defensive — Literal should prevent this
        return AnswerPayload(
            answer=_format_unsupported(QueryInterpretation(
                bucket="unsupported",
                unsupported_reason=f"unknown bucket: {interpretation.bucket}",
            )),
            answer_type="unsupported",
            citations=[],
            interpretation=interpretation,
            extraction_min=None,
            answer_certainty="low",
        )

    data = executor(interpretation, elements)
    formatter = _FORMATTERS[interpretation.bucket]
    prose = formatter(data, interpretation.filter)

    return AnswerPayload(
        answer=prose,
        answer_type=interpretation.bucket,
        citations=data.citations,
        interpretation=interpretation,
        extraction_min=data.extraction_min,
        answer_certainty=data.answer_certainty,
    )


_FORMATTERS = {
    "count": _format_count,
    "quantity": _format_quantity,
    "rank": _format_rank,
    "adjacency": _format_adjacency,
    "lookup": _format_lookup,
}


def _default_context(elements: list[Any]) -> dict[str, Any]:
    """Summary of what's in the drawing — hint for the interpreter."""
    kinds: dict[str, int] = {}
    for e in elements:
        k = _attr(e, "kind") or "unknown"
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "kinds_present": sorted(kinds.keys()),
        "counts_by_kind": kinds,
        "room_count": kinds.get("room", 0),
    }
