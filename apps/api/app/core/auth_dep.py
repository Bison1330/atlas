"""FastAPI dependencies that thread the authenticated user through routes.

Three dependencies:

- :func:`current_user` — reads the session cookie, validates it,
  hydrates the User row. 401 on any failure.
- :func:`require_csrf` — checks the double-submit cookie-vs-header
  contract on mutating requests (POST/PATCH/PUT/DELETE). 403 on
  mismatch.
- :func:`owned_drawing_for_read` / :func:`owned_drawing_for_write`
  — path-param dependencies that resolve a drawing and enforce
  the read / write ownership rules from the service layer.

The dependencies touch only well-understood primitives:
``request.cookies``, ``request.headers``, DB, Redis. No global
state. Tests override them via ``app.dependency_overrides`` when
a specific auth state is needed.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.sessions import read_session, touch_session
from app.db import Drawing, User
from app.schemas.errors import APIError
from app.services import auth as auth_svc


def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the authenticated user or 401.

    Extracts the signed cookie, validates it, bumps the Redis TTL
    (sliding-window session), then loads the User row. Any failure
    — missing cookie, bad signature, expired session, deleted user
    — returns 401 with a uniform ``not_authenticated`` body.
    """
    settings = get_settings()
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        raise APIError(
            code="not_authenticated",
            message="Authentication required.",
            status_code=401,
        )

    resolved = read_session(cookie)
    if resolved is None:
        raise APIError(
            code="not_authenticated",
            message="Session is invalid or expired.",
            status_code=401,
        )
    raw_id, record = resolved
    touch_session(raw_id)

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        # Session referred to a user that's gone / deactivated.
        # Treat identically to bad auth — don't leak the distinction.
        raise APIError(
            code="not_authenticated",
            message="Session is invalid or expired.",
            status_code=401,
        )
    return user


def require_csrf(request: Request) -> None:
    """Enforce the CSRF double-submit contract on mutating requests.

    Protected methods: POST, PATCH, PUT, DELETE. GET/HEAD/OPTIONS
    bypass (they're not state-changing). The incoming
    ``X-Atlas-CSRF`` header must exactly match the value of the
    non-HttpOnly ``atlas_csrf`` cookie. Absence of either is a
    403 with ``csrf_failed``.

    The token itself is opaque and rotates on every login — the
    server doesn't validate its content, only that the header and
    cookie agree. This is the standard double-submit pattern.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    settings = get_settings()
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(settings.csrf_header_name)

    if not cookie_token or not header_token:
        raise APIError(
            code="csrf_failed",
            message="CSRF token missing.",
            status_code=403,
        )
    # Constant-time compare — a timing oracle on a public CSRF
    # token is extremely low-value, but the primitive is cheap.
    import hmac
    if not hmac.compare_digest(cookie_token, header_token):
        raise APIError(
            code="csrf_failed",
            message="CSRF token mismatch.",
            status_code=403,
        )


def owned_drawing_for_read(
    drawing_id: UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Drawing:
    """Path-param resolver: 404 unless caller can read this drawing."""
    return auth_svc.drawing_readable_by(db, drawing_id, user)


def owned_drawing_for_write(
    drawing_id: UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Drawing:
    """Path-param resolver: owner-only write access; 409 on unclaimed."""
    return auth_svc.drawing_writable_by(db, drawing_id, user)
