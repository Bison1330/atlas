"""HTTP surface for projects + membership + drawing assignment (M8).

Endpoints (see ``docs/research/m8-projects.md`` for rationale):

- ``POST  /projects`` — creator auto-added as member.
- ``GET   /projects`` — list projects I'm a member of.
- ``GET   /projects/{id}`` — detail with member list + counts;
  ``warnings.flat_membership`` flag surfaces the M8 caveat so
  every UI rendering this response knows about it.
- ``PATCH /projects/{id}`` — update name / description.
- ``POST  /projects/{id}/members`` — add by user_id OR email;
  rate-limited (10 adds per project per minute).
- ``DELETE /projects/{id}/members/{user_id}`` — remove (anyone
  may remove anyone in v1; M8.1 role-gates this).
- ``PATCH /drawings/{id}/project`` — assign/unassign a drawing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.auth_dep import current_user, require_csrf
from app.core.db import get_db
from app.core.rate_limit import check_and_increment
from app.db import User
from app.schemas.errors import APIError
from app.services import projects as svc

project_router = APIRouter(prefix="/projects", tags=["projects"])
drawing_assignment_router = APIRouter(prefix="/drawings", tags=["projects"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)


class MemberIn(BaseModel):
    """Add-a-member payload — exactly one of user_id or email."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    email: EmailStr | None = None


class MemberOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    email: str
    display_name: str | None = None
    joined_at: datetime


class ProjectWarnings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Flat-membership caveat (see M8 research §9.3): any member can
    # add / remove any other member. UIs should surface this.
    flat_membership: bool = True


class ProjectOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    member_count: int
    drawing_count: int
    members: list[MemberOut] = Field(default_factory=list)
    warnings: ProjectWarnings = Field(default_factory=ProjectWarnings)


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectSummary] = Field(default_factory=list)


class DrawingAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # null = unassign from any project.
    project_id: UUID | None = None


class DrawingAssignmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID
    project_id: UUID | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_project_out(db: Session, project) -> ProjectOut:
    members = [
        MemberOut(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            joined_at=pm.joined_at,
        )
        for pm, u in svc.list_members(db, project.id)
    ]
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        member_count=len(members),
        drawing_count=svc.drawing_count(db, project.id),
        members=members,
    )


def _client_ip(request: Request) -> str:
    client = request.client
    return client.host if client else "-"


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


@project_router.post(
    "",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project; creator is auto-added as a member.",
)
def create_project(
    body: ProjectCreate,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ProjectOut:
    p = svc.create_project(
        db, name=body.name, description=body.description, creator=user,
    )
    return _build_project_out(db, p)


@project_router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects the caller is a member of.",
)
def list_projects(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ProjectListResponse:
    rows = svc.list_for_user(db, user)
    return ProjectListResponse(
        projects=[
            ProjectSummary(
                id=p.id, name=p.name, description=p.description,
                created_by=p.created_by,
                created_at=p.created_at, updated_at=p.updated_at,
            )
            for p in rows
        ],
    )


@project_router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Project detail with member list and counts.",
)
def get_project(
    project_id: UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ProjectOut:
    p = svc.get_project_readable_by(db, project_id, user)
    return _build_project_out(db, p)


@project_router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Update a project's name/description (any member).",
)
def patch_project(
    project_id: UUID,
    body: ProjectUpdate,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ProjectOut:
    p = svc.update_project(
        db, project_id, user,
        name=body.name, description=body.description,
    )
    return _build_project_out(db, p)


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


@project_router.post(
    "/{project_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a user to a project (by user_id or email).",
)
def add_member(
    project_id: UUID,
    body: MemberIn,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> MemberOut:
    # Rate-limit per (project, ip) to blunt the email-enumeration
    # surface (see research §9.4).
    current_count, limit, retry_after = check_and_increment(
        scope="projects:add_member",
        identifier=f"{project_id}:{_client_ip(request)}",
        limit=10,
        window_seconds=60,
    )
    if current_count > limit:
        response.headers["Retry-After"] = str(retry_after)
        raise APIError(
            code="rate_limited",
            message="Too many member-add attempts. Try again shortly.",
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )

    target = svc.add_member(
        db, project_id,
        caller=user,
        target_user_id=body.user_id,
        target_email=(str(body.email) if body.email else None),
    )
    # Look up the freshly-inserted row's joined_at via list_members.
    members = [
        (pm, u) for pm, u in svc.list_members(db, project_id)
        if u.id == target.id
    ]
    pm, u = members[0]
    return MemberOut(
        user_id=u.id, email=u.email, display_name=u.display_name,
        joined_at=pm.joined_at,
    )


@project_router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a user from a project (flat — any member).",
)
def remove_member(
    project_id: UUID,
    user_id: UUID,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> None:
    svc.remove_member(db, project_id, user_id, user)


# ---------------------------------------------------------------------------
# Drawing assignment
# ---------------------------------------------------------------------------


@drawing_assignment_router.patch(
    "/{drawing_id}/project",
    response_model=DrawingAssignmentOut,
    summary="Assign or unassign a drawing's project.",
)
def patch_drawing_project(
    drawing_id: UUID,
    body: DrawingAssignmentIn,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> DrawingAssignmentOut:
    d = svc.set_drawing_project(db, drawing_id, body.project_id, user)
    return DrawingAssignmentOut(
        drawing_id=d.id,
        project_id=d.project_id,
    )
