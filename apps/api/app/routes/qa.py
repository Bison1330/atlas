"""Q&A endpoint — ask a question of a drawing, get a grounded answer.

``POST /drawings/{drawing_id}/ask`` runs the M5 Q&A pipeline:

1. Resolve the latest completed ``ElementSource`` for the drawing
   (or an explicit one via request body), fetch all its elements.
2. Hand off to :func:`app.services.qa.ask` with a real Claude
   interpreter. Returns the structured answer + citations +
   interpretation + confidence.

Why POST (not GET): the question goes in the request body so it
isn't accidentally indexed/logged as a URL param, and a future
multi-turn version can add ``conversation_id`` + prior turns
without reshaping the contract.

The endpoint returns 503 when ``ANTHROPIC_API_KEY`` is unset —
local dev without a key sees a clear failure mode instead of an
opaque one. Everything else in the API keeps working.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.db import Drawing, Element, ElementSource, Sheet
from app.schemas.errors import NotFoundError, ServiceError
from app.services import qa as qa_svc
from app.services.qa_interpreter import ClaudeInterpreter

router = APIRouter(prefix="/drawings", tags=["qa"])


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    source_id: UUID | None = None


class CitationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: UUID
    sheet_id: UUID
    kind: str
    ncs_layer: str | None = None
    bbox: dict[str, float] | None = None
    display_label: str


class QueryInterpretationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket: str
    filter: dict[str, Any] = Field(default_factory=dict)
    unsupported_reason: str | None = None
    suggested_phrasing: str | None = None


class ConfidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction_min: float | None = None
    answer_certainty: str


class AskMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID | None
    # Phase-3 gating flag — flips to "validated" once a Tier 2
    # extraction eval passes. Until then, every response carries
    # the honest caveat. See docs/research/m4-phase3-procurement.md.
    extraction_status: str = "unvalidated_on_real_drawings"
    interpreter_model: str | None = None


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    answer_type: str
    citations: list[CitationOut] = Field(default_factory=list)
    query_interpretation: QueryInterpretationOut
    confidence: ConfidenceOut
    meta: AskMeta


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def _get_interpreter() -> qa_svc.Interpreter:
    """Dependency — provides the real Claude interpreter.

    Tests override this via ``app.dependency_overrides`` to inject
    a :class:`FakeInterpreter`; see ``tests/test_qa_api.py``.
    Factored as a function (not a module-level singleton) so each
    request can re-read settings — relevant for test scenarios that
    patch env vars.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ServiceError(
            code="llm_unavailable",
            message=(
                "Q&A is unavailable — ANTHROPIC_API_KEY is not set on "
                "the API service. Set the env var and retry."
            ),
            status_code=503,
        )
    return ClaudeInterpreter(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
    )


@router.post(
    "/{drawing_id}/ask",
    response_model=AskResponse,
    summary="Ask a question of a drawing; get a grounded, cited answer.",
)
def ask_drawing(
    drawing_id: UUID,
    body: AskRequest,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
    interpreter: Annotated[
        qa_svc.Interpreter, Depends(_get_interpreter)
    ] = None,  # type: ignore[assignment]
) -> AskResponse:
    drawing = db.get(Drawing, drawing_id)
    if drawing is None:
        raise NotFoundError("Drawing", str(drawing_id))

    source_id = body.source_id or _latest_completed_source_id(db, drawing_id)
    elements: list[Element] = []
    if source_id is not None:
        elements = list(db.execute(
            select(Element)
            .join(Sheet, Element.sheet_id == Sheet.id)
            .where(
                Sheet.drawing_id == drawing_id,
                Element.source_id == source_id,
            )
        ).scalars().all())

    payload = qa_svc.ask(body.question, elements, interpreter)

    return AskResponse(
        answer=payload.answer,
        answer_type=payload.answer_type,
        citations=[
            CitationOut(
                element_id=c.element_id,
                sheet_id=c.sheet_id,
                kind=c.kind,
                ncs_layer=c.ncs_layer,
                bbox=c.bbox,
                display_label=c.display_label,
            )
            for c in payload.citations
        ],
        query_interpretation=QueryInterpretationOut(
            bucket=payload.interpretation.bucket,
            filter=payload.interpretation.filter,
            unsupported_reason=payload.interpretation.unsupported_reason,
            suggested_phrasing=payload.interpretation.suggested_phrasing,
        ),
        confidence=ConfidenceOut(
            extraction_min=payload.extraction_min,
            answer_certainty=payload.answer_certainty,
        ),
        meta=AskMeta(
            source_id=source_id,
            interpreter_model=get_settings().anthropic_model,
        ),
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
