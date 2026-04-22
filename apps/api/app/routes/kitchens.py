"""HTTP surface for the V1 kitchen design system (Session 1).

Endpoints (all under prefix ``/app/kitchens``; the ``/app`` prefix
mirrors the frontend route structure so every kitchen surface reads
the same URL top-to-bottom):

- ``POST /app/kitchens`` — start a new kitchen project. Creates the
  ``Project`` row (owner auto-added as member), the ``KitchenBrief``,
  records the user's first message, and returns Atlas's first
  assistant turn with whatever fields the intake model extracted.
- ``POST /app/kitchens/{project_id}/messages`` — continue the
  conversation. Loads full history, calls Opus, persists the
  assistant turn + any extracted delta.
- ``GET /app/kitchens/{project_id}`` — full state: project, brief,
  messages, extracted fields, completion flag.
- ``GET /app/kitchens`` — list the caller's kitchen projects.

Session 1 stops at ``is_complete=True``. Generation (S3) wires into
the same brief row; the UI shows a "Coming soon" card once complete.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth_dep import (
    current_user,
    owned_project_for_read,
    require_csrf,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import check_and_increment
from app.db import KitchenBrief, KitchenBriefMessage, Project, User
from app.schemas.errors import APIError, ServiceError
from app.services import projects as projects_svc
from app.services.kitchen_intake import (
    ClaudeKitchenIntake,
    IntakeTurnResult,
    KitchenIntake,
)

router = APIRouter(prefix="/app/kitchens", tags=["kitchens"])


# ---------------------------------------------------------------------------
# Allowed project types at /app/kitchens/… today. V1 is kitchen-only; the
# pills for bathroom/retail/office are disabled in the UI. We still validate
# here so a future client that tries one fails loudly.
# ---------------------------------------------------------------------------

_V1_KITCHEN_TYPES = {"kitchen_remodel", "kitchen_new"}

# Per-user intake budget. Kevin's guidance: don't over-optimize for
# pennies (S0 answer #3). 60/min is loose enough that no real user
# hits it, tight enough to deter a runaway client.
_MESSAGE_RATE_LIMIT_PER_MIN = 60
_RATE_WINDOW_SECONDS = 60


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class KitchenStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: str = Field(
        description="V1: kitchen_remodel or kitchen_new.",
    )
    initial_message: str = Field(min_length=1, max_length=8000)
    # Optional human-readable project name. If omitted the API
    # derives one from the first few words of initial_message.
    name: str | None = Field(default=None, min_length=1, max_length=120)


class KitchenMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=8000)


class MessageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: str
    content: str
    extracted_delta: dict[str, Any] | None = None
    created_at: datetime


class BriefOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    status: str
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    superseded_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ProjectShort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    project_type: str | None
    lifecycle_state: str | None
    created_at: datetime
    updated_at: datetime


class KitchenStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectShort
    brief: BriefOut
    atlas_response: str
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    is_complete: bool


class KitchenMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atlas_response: str
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    extracted_delta: dict[str, Any] | None = None
    is_complete: bool


class KitchenDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectShort
    brief: BriefOut
    messages: list[MessageOut] = Field(default_factory=list)
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    is_complete: bool


class KitchenListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectShort] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Intake provider (overridable for tests)
# ---------------------------------------------------------------------------


def _get_kitchen_intake() -> KitchenIntake:
    """Dependency — provides the real Opus intake.

    Tests override this via ``app.dependency_overrides`` to inject
    :class:`FakeKitchenIntake`. Factored as a function (not a
    module-level singleton) so each request re-reads settings.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ServiceError(
            code="llm_unavailable",
            message=(
                "Kitchen intake is unavailable — ANTHROPIC_API_KEY is "
                "not set on the API service."
            ),
            status_code=503,
        )
    return ClaudeKitchenIntake(api_key=settings.anthropic_api_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_project_name(message: str) -> str:
    """Make a short project name out of the user's first sentence."""
    stripped = " ".join(message.strip().split())
    if not stripped:
        return "New kitchen"
    # First 60 chars or the first sentence, whichever shorter.
    chunk = stripped.split(".")[0].split("?")[0].strip()
    if not chunk:
        chunk = stripped
    if len(chunk) > 60:
        chunk = chunk[:57].rstrip() + "…"
    return chunk


def _load_messages(db: Session, brief_id: UUID) -> list[KitchenBriefMessage]:
    return list(db.execute(
        select(KitchenBriefMessage)
        .where(KitchenBriefMessage.brief_id == brief_id)
        .order_by(KitchenBriefMessage.created_at.asc())
    ).scalars().all())


def _load_current_brief(db: Session, project_id: UUID) -> KitchenBrief | None:
    """Latest non-superseded brief for a project.

    V1: at most one brief per project; M-series refinement will build
    on the ``superseded_by`` chain and pick the head of the chain.
    """
    return db.execute(
        select(KitchenBrief)
        .where(
            KitchenBrief.project_id == project_id,
            KitchenBrief.superseded_by.is_(None),
        )
        .order_by(KitchenBrief.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _intake_messages(messages: list[KitchenBriefMessage]) -> list[dict[str, Any]]:
    """Turn DB rows into the Anthropic messages array.

    Role coercion: ``user`` and ``assistant`` pass through; ``system``
    roles are skipped (the system prompt goes in the `system` param,
    not the messages list).
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role in ("user", "assistant"):
            out.append({"role": m.role, "content": m.content})
    return out


def _as_brief_out(brief: KitchenBrief) -> BriefOut:
    return BriefOut(
        id=brief.id,
        project_id=brief.project_id,
        status=brief.status,
        extracted_fields=brief.extracted_fields or {},
        superseded_by=brief.superseded_by,
        created_at=brief.created_at,
        updated_at=brief.updated_at,
    )


def _as_project_short(project: Project) -> ProjectShort:
    return ProjectShort(
        id=project.id,
        name=project.name,
        project_type=project.project_type,
        lifecycle_state=project.lifecycle_state,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _apply_intake_result(
    db: Session,
    brief: KitchenBrief,
    project: Project,
    result: IntakeTurnResult,
) -> dict[str, Any] | None:
    """Persist one assistant turn into the brief + messages tables.

    Returns the ``extracted_delta`` saved on the message row (None
    when the turn produced no structured update).
    """
    delta: dict[str, Any] | None = None
    if result.field_updates:
        merged = dict(brief.extracted_fields or {})
        merged.update(result.field_updates)
        brief.extracted_fields = merged
        delta = dict(result.field_updates)

    if result.is_complete:
        brief.status = "complete"
        project.lifecycle_state = "brief_complete"
        if result.completion_summary:
            # Stash the completion summary under a reserved key so
            # the UI can surface Atlas's final recap without mixing
            # with live-extracted fields.
            merged = dict(brief.extracted_fields or {})
            merged["_completion_summary"] = result.completion_summary
            brief.extracted_fields = merged

    # Assistant's message (if any — rarely empty when tools were
    # called without text).
    text = result.assistant_message or ""
    if text:
        db.add(KitchenBriefMessage(
            id=uuid4(),
            brief_id=brief.id,
            role="assistant",
            content=text,
            extracted_delta=delta,
        ))

    db.add(brief)
    db.add(project)
    return delta


def _rate_limit_intake(user_id: UUID, project_id: UUID) -> None:
    """60/min per user per project — gates Opus token spend.

    Identifier is ``(project_id, user_id)`` so different projects in
    the same session don't share a bucket. The APIError carries
    ``Retry-After`` via the headers kwarg; the exception handler
    rebuilds its own JSONResponse, so ``response.headers[...]`` at
    the route level is silently dropped.
    """
    current_count, limit, retry_after = check_and_increment(
        scope="kitchens:intake_messages",
        identifier=f"{project_id}:{user_id}",
        limit=_MESSAGE_RATE_LIMIT_PER_MIN,
        window_seconds=_RATE_WINDOW_SECONDS,
    )
    if current_count > limit:
        raise APIError(
            code="rate_limited",
            message=(
                "Too many intake messages in a short period. "
                "Try again in a minute."
            ),
            status_code=429,
            details={"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=KitchenStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new kitchen project and seed the intake conversation.",
)
def start_kitchen(
    body: KitchenStartRequest,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
    intake: Annotated[
        KitchenIntake, Depends(_get_kitchen_intake)
    ] = None,  # type: ignore[assignment]
) -> KitchenStartResponse:
    if body.project_type not in _V1_KITCHEN_TYPES:
        raise APIError(
            code="unsupported_project_type",
            message=(
                "Only kitchen projects are supported in V1. "
                f"Got: {body.project_type!r}."
            ),
            status_code=422,
        )

    # Pre-rate-limit keyed by user+IP-ish (user alone is fine here
    # because we don't have a project yet). This stops a runaway
    # client from creating a mountain of orphan projects at the
    # rate limit's expense.
    start_count, start_limit, retry_after = check_and_increment(
        scope="kitchens:starts",
        identifier=str(user.id),
        limit=_MESSAGE_RATE_LIMIT_PER_MIN,
        window_seconds=_RATE_WINDOW_SECONDS,
    )
    if start_count > start_limit:
        raise APIError(
            code="rate_limited",
            message=(
                "Too many projects started in a short period. "
                "Try again in a minute."
            ),
            status_code=429,
            details={"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    project_name = body.name or _derive_project_name(body.initial_message)
    project = projects_svc.create_project(
        db, name=project_name, description=None, creator=user,
    )
    project.project_type = body.project_type
    project.lifecycle_state = "brief_drafting"
    db.add(project)

    brief = KitchenBrief(
        id=uuid4(),
        project_id=project.id,
        status="drafting",
        extracted_fields={},
    )
    db.add(brief)
    db.flush()

    db.add(KitchenBriefMessage(
        id=uuid4(),
        brief_id=brief.id,
        role="user",
        content=body.initial_message,
    ))
    db.flush()

    history = _intake_messages(_load_messages(db, brief.id))
    result = intake.send_turn(history)
    _apply_intake_result(db, brief, project, result)

    db.commit()
    db.refresh(project)
    db.refresh(brief)

    return KitchenStartResponse(
        project=_as_project_short(project),
        brief=_as_brief_out(brief),
        atlas_response=result.assistant_message,
        extracted_fields=brief.extracted_fields or {},
        is_complete=brief.status == "complete",
    )


@router.post(
    "/{project_id}/messages",
    response_model=KitchenMessageResponse,
    summary="Send a user message in the intake conversation.",
)
def send_message(
    body: KitchenMessageRequest,
    user: Annotated[User, Depends(current_user)],
    project: Annotated[Project, Depends(owned_project_for_read)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
    intake: Annotated[
        KitchenIntake, Depends(_get_kitchen_intake)
    ] = None,  # type: ignore[assignment]
) -> KitchenMessageResponse:
    brief = _load_current_brief(db, project.id)
    if brief is None:
        raise APIError(
            code="no_active_brief",
            message="This project has no active kitchen brief.",
            status_code=409,
        )
    if brief.status == "complete":
        raise APIError(
            code="brief_complete",
            message=(
                "Intake is already complete for this project. "
                "Refinement arrives with S9."
            ),
            status_code=409,
        )

    _rate_limit_intake(user.id, project.id)

    db.add(KitchenBriefMessage(
        id=uuid4(),
        brief_id=brief.id,
        role="user",
        content=body.content,
    ))
    db.flush()

    history = _intake_messages(_load_messages(db, brief.id))
    result = intake.send_turn(history)
    delta = _apply_intake_result(db, brief, project, result)

    db.commit()
    db.refresh(brief)
    db.refresh(project)

    return KitchenMessageResponse(
        atlas_response=result.assistant_message,
        extracted_fields=brief.extracted_fields or {},
        extracted_delta=delta,
        is_complete=brief.status == "complete",
    )


@router.get(
    "/{project_id}",
    response_model=KitchenDetailResponse,
    summary="Full state of a kitchen project: brief + messages.",
)
def get_kitchen(
    user: Annotated[User, Depends(current_user)],
    project: Annotated[Project, Depends(owned_project_for_read)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> KitchenDetailResponse:
    brief = _load_current_brief(db, project.id)
    if brief is None:
        raise APIError(
            code="no_active_brief",
            message="This project has no active kitchen brief.",
            status_code=404,
        )
    raw_messages = _load_messages(db, brief.id)
    return KitchenDetailResponse(
        project=_as_project_short(project),
        brief=_as_brief_out(brief),
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                extracted_delta=m.extracted_delta,
                created_at=m.created_at,
            )
            for m in raw_messages
        ],
        extracted_fields=brief.extracted_fields or {},
        is_complete=brief.status == "complete",
    )


@router.get(
    "",
    response_model=KitchenListResponse,
    summary="List the caller's kitchen projects (newest first).",
)
def list_kitchens(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> KitchenListResponse:
    rows = projects_svc.list_for_user(db, user)
    kitchens = [
        p for p in rows
        if p.project_type in _V1_KITCHEN_TYPES
    ]
    return KitchenListResponse(
        projects=[_as_project_short(p) for p in kitchens],
    )
