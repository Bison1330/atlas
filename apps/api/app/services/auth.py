"""Auth business logic (M7).

Pure-ish service layer — routes own the session/cookie wiring and
pass in the DB session + request metadata. The service handles:

- Registration: policy check → hash → insert row. ``IntegrityError``
  on the unique email index surfaces as ``email_taken``.
- Login: look up user by email, verify password, regenerate a
  fresh session, bump ``last_login_at``. On wrong password we run
  :func:`dummy_verify` so the latency matches the success path
  (blocks email-enumeration by timing).
- Ownership: helpers that resolve a drawing for the caller
  (returns 404 on nonexistent, 403 on "exists but not yours",
  200 on owned, 200 on null-owned reads).

The service stays agnostic to FastAPI — the route layer handles
all the cookie / HTTP mechanics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.passwords import (
    WeakPasswordError,
    dummy_verify,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.db import Drawing, ProjectMember, User
from app.schemas.errors import APIError, NotFoundError


def _normalize_email(raw: str) -> str:
    """Lowercase + strip + validate — raises APIError on garbage."""
    try:
        info = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise APIError(
            code="invalid_email",
            message=f"Email address is not valid: {exc}",
            status_code=422,
        ) from exc
    return info.normalized.lower()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
) -> User:
    """Create a new user row.

    Raises:
        APIError(422, invalid_email): email can't be parsed.
        APIError(422, weak_password): policy rejection
            (too short / common-breached).
        APIError(409, email_taken): unique-email collision.
    """
    normalized_email = _normalize_email(email)
    try:
        pw_hash = hash_password(password)
    except WeakPasswordError as exc:
        raise APIError(
            code=exc.reason,
            message=exc.user_message,
            status_code=422,
        ) from exc

    user = User(
        email=normalized_email,
        password_hash=pw_hash,
        display_name=(display_name or None),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise APIError(
            code="email_taken",
            message="An account with that email already exists.",
            status_code=409,
        ) from exc
    session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def authenticate(
    session: Session,
    *,
    email: str,
    password: str,
) -> User | None:
    """Verify credentials. Returns the User on success, None on failure.

    Runs :func:`dummy_verify` on the "user not found" branch so the
    caller cannot distinguish it from "wrong password" by timing.

    On success, transparently re-hashes the password if the stored
    hash was made with outdated argon2 parameters (D-12 — keeps the
    system's security posture aligned with the current config).
    """
    try:
        normalized_email = _normalize_email(email)
    except APIError:
        # Email doesn't parse — still pay the dummy cost so the
        # "invalid_email" vs "no_such_user" distinction isn't a
        # timing oracle.
        dummy_verify()
        return None

    user = session.execute(
        select(User).where(User.email == normalized_email)
    ).scalar_one_or_none()

    if user is None:
        dummy_verify()
        return None
    if not user.is_active:
        dummy_verify()
        return None

    if not verify_password(password, user.password_hash):
        return None

    if needs_rehash(user.password_hash):
        try:
            user.password_hash = hash_password(password)
        except WeakPasswordError:
            # User's existing password no longer meets policy; we
            # still let them log in, but they can't re-register
            # the same password. A forced-reset flow can layer on
            # later.
            pass

    user.last_login_at = datetime.now(UTC)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Ownership checks (drawings)
# ---------------------------------------------------------------------------


def _is_project_member(
    session: Session, project_id: UUID, user_id: UUID,
) -> bool:
    """Row-exists check against ``project_members``. Returns ``False``
    for ``project_id=None`` so callers can pass a drawing's project_id
    directly."""
    if project_id is None:
        return False
    return session.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).scalar_one_or_none() is not None


def drawing_readable_by(
    session: Session, drawing_id: UUID, user: User,
) -> Drawing:
    """Resolve a drawing the user is allowed to *read*.

    Read access (M8 update):
    - owner_id = user, OR
    - unclaimed (owner_id IS NULL), OR
    - drawing is assigned to a project the user is a member of.

    NotFound (not 403) for drawings owned by others and not shared
    via any project the user belongs to — we don't signal existence.
    """
    d = session.get(Drawing, drawing_id)
    if d is None:
        raise NotFoundError("Drawing", str(drawing_id))
    if d.owner_id is None:
        return d
    if d.owner_id == user.id:
        return d
    if d.project_id is not None and _is_project_member(
        session, d.project_id, user.id,
    ):
        return d
    raise NotFoundError("Drawing", str(drawing_id))


def drawing_writable_by(
    session: Session, drawing_id: UUID, user: User,
) -> Drawing:
    """Resolve a drawing the user is allowed to *mutate*.

    Write access (M8 update):
    - owner_id = user, OR
    - drawing is assigned to a project the user is a member of.

    Unclaimed drawings need to be claimed via
    ``POST /drawings/{id}/claim`` before writes land.
    """
    d = session.get(Drawing, drawing_id)
    if d is None:
        raise NotFoundError("Drawing", str(drawing_id))
    if d.owner_id is None:
        raise APIError(
            code="drawing_unclaimed",
            message=(
                "This drawing has no owner. Claim it first via "
                f"POST /drawings/{drawing_id}/claim."
            ),
            status_code=409,
        )
    if d.owner_id == user.id:
        return d
    if d.project_id is not None and _is_project_member(
        session, d.project_id, user.id,
    ):
        return d
    raise NotFoundError("Drawing", str(drawing_id))


def claim_drawing(
    session: Session, drawing_id: UUID, user: User,
) -> Drawing:
    """Assign ownership of an unclaimed drawing to the caller.

    Idempotent for the *same* caller: claiming a drawing you already
    own returns it unchanged. Raises when the drawing exists but
    belongs to someone else.
    """
    d = session.get(Drawing, drawing_id)
    if d is None:
        raise NotFoundError("Drawing", str(drawing_id))
    if d.owner_id == user.id:
        return d
    if d.owner_id is not None:
        raise APIError(
            code="drawing_already_owned",
            message="This drawing already has an owner.",
            status_code=409,
        )
    d.owner_id = user.id
    session.add(d)
    session.commit()
    session.refresh(d)
    return d
