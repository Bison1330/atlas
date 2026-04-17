"""Project + membership CRUD (M8).

Flat membership (D-15) — row existence means member. No roles
yet; M8.1 layers the role column and permission gates on top.

Service keeps DB ownership with the route (same pattern as other
services). Membership checks use the shared helper from
``app.services.auth`` so ownership semantics stay in one place.
"""

from __future__ import annotations

from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Drawing, Project, ProjectMember, User
from app.schemas.errors import APIError, NotFoundError
from app.services.auth import _is_project_member


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


def create_project(
    session: Session,
    *,
    name: str,
    description: str | None,
    creator: User,
) -> Project:
    """Create a new project; creator is auto-added as the first member."""
    project = Project(
        name=name,
        description=description,
        created_by=creator.id,
    )
    session.add(project)
    session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=creator.id))
    session.commit()
    session.refresh(project)
    return project


def list_for_user(session: Session, user: User) -> list[Project]:
    """Projects the user is a member of, newest first."""
    return list(session.execute(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.created_at.desc())
    ).scalars().all())


def get_project_readable_by(
    session: Session, project_id: UUID, user: User,
) -> Project:
    """Fetch a project the caller is a member of. 404 otherwise.

    Non-members can't confirm the project exists — symmetric with
    the drawing access rules.
    """
    p = session.get(Project, project_id)
    if p is None:
        raise NotFoundError("Project", str(project_id))
    if not _is_project_member(session, p.id, user.id):
        raise NotFoundError("Project", str(project_id))
    return p


def update_project(
    session: Session,
    project_id: UUID,
    user: User,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    p = get_project_readable_by(session, project_id, user)
    if name is not None:
        p.name = name
    if description is not None:
        p.description = description
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


def list_members(session: Session, project_id: UUID) -> list[tuple[ProjectMember, User]]:
    rows = session.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.joined_at.asc())
    ).all()
    return [(pm, u) for pm, u in rows]


def add_member(
    session: Session,
    project_id: UUID,
    *,
    caller: User,
    target_user_id: UUID | None = None,
    target_email: str | None = None,
) -> User:
    """Add a user to a project — either by ID or by email (but not
    both).

    Raises:
        NotFoundError: caller isn't a member, target user not found.
        APIError(409, already_member): target is already in the
            project.
        APIError(400, missing_target): neither id nor email given.
    """
    # Caller must be an existing member (flat policy — M8.1 gates
    # this further by role).
    get_project_readable_by(session, project_id, caller)

    if target_user_id is None and target_email is None:
        raise APIError(
            code="missing_target",
            message="Provide either user_id or email.",
            status_code=400,
        )
    target = _resolve_user(session, user_id=target_user_id, email=target_email)

    if _is_project_member(session, project_id, target.id):
        raise APIError(
            code="already_member",
            message="That user is already a member of this project.",
            status_code=409,
            details={"user_id": str(target.id)},
        )
    session.add(ProjectMember(project_id=project_id, user_id=target.id))
    session.commit()
    return target


def remove_member(
    session: Session,
    project_id: UUID,
    target_user_id: UUID,
    caller: User,
) -> None:
    """Remove a user. Any member may remove any member in M8 (flat).

    Warning surfaced in the project-detail response makes this
    visible to UIs; M8.1 adds role gating.
    """
    get_project_readable_by(session, project_id, caller)
    row = session.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == target_user_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("ProjectMember", str(target_user_id))
    session.delete(row)
    session.commit()


# ---------------------------------------------------------------------------
# Drawing assignment
# ---------------------------------------------------------------------------


def set_drawing_project(
    session: Session,
    drawing_id: UUID,
    new_project_id: UUID | None,
    caller: User,
) -> Drawing:
    """Assign or unassign a drawing's project.

    Rules:
    - caller must own the drawing (not just be a project member);
    - if setting a project, caller must be a member of that project
      too.
    """
    d = session.get(Drawing, drawing_id)
    if d is None:
        raise NotFoundError("Drawing", str(drawing_id))
    if d.owner_id != caller.id:
        # Matches the "404-on-not-yours" policy used elsewhere.
        raise NotFoundError("Drawing", str(drawing_id))

    if new_project_id is not None:
        if not _is_project_member(session, new_project_id, caller.id):
            raise APIError(
                code="not_project_member",
                message=(
                    "You must be a member of the target project to "
                    "assign a drawing to it."
                ),
                status_code=403,
            )
    d.project_id = new_project_id
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


# ---------------------------------------------------------------------------
# Counts (for the detail response)
# ---------------------------------------------------------------------------


def member_count(session: Session, project_id: UUID) -> int:
    return int(session.execute(
        select(func.count()).where(ProjectMember.project_id == project_id)
    ).scalar_one())


def drawing_count(session: Session, project_id: UUID) -> int:
    return int(session.execute(
        select(func.count()).where(Drawing.project_id == project_id)
    ).scalar_one())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_user(
    session: Session,
    *,
    user_id: UUID | None,
    email: str | None,
) -> User:
    if user_id is not None:
        u = session.get(User, user_id)
        if u is None or not u.is_active:
            raise NotFoundError("User", str(user_id))
        return u
    # Email branch.
    try:
        normalized = validate_email(
            (email or "").strip(), check_deliverability=False,
        ).normalized.lower()
    except EmailNotValidError as exc:
        raise APIError(
            code="invalid_email",
            message=f"Email address is not valid: {exc}",
            status_code=422,
        ) from exc
    u = session.execute(
        select(User).where(User.email == normalized)
    ).scalar_one_or_none()
    if u is None or not u.is_active:
        raise NotFoundError("User", normalized)
    return u
