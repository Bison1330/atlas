"""Auth HTTP surface (M7).

Endpoints:

- ``POST /auth/register`` — create account + log in.
- ``POST /auth/login`` — password-verify + issue session cookie.
- ``POST /auth/logout`` — clear session + cookie.
- ``GET  /auth/me`` — current user summary (401 if not logged in).
- ``POST /drawings/{id}/claim`` — take ownership of an unclaimed
  drawing (legacy / pre-M7 data).

Cookie mechanics live here rather than in the service layer so
the service stays easy to unit-test. The service does everything
that doesn't need a ``Request`` / ``Response``; the route adds the
HTTP plumbing.

Rate limits (Redis-backed counters):

- Login: 5 attempts per ``(email_hash, ip)`` per 15 minutes.
- Register: 3 attempts per IP per hour.

The ``Retry-After`` header on 429 responses tells the client when
the window resets.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.auth_dep import current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import check_and_increment, reset
from app.core.sessions import (
    create_session,
    destroy_session,
    generate_csrf_token,
    read_session,
)
from app.db import Drawing, User
from app.schemas.errors import APIError
from app.services import auth as auth_svc

auth_router = APIRouter(prefix="/auth", tags=["auth"])
drawing_claim_router = APIRouter(prefix="/drawings", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    email: str
    email_verified: bool
    display_name: str | None = None
    is_active: bool
    last_login_at: datetime | None = None


class DrawingClaimOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID
    owner_id: UUID


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _set_session_cookies(response: Response, *, signed_session: str, csrf: str) -> None:
    settings = get_settings()
    secure = settings.is_production
    response.set_cookie(
        key=settings.session_cookie_name,
        value=signed_session,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    # CSRF token is deliberately *not* HttpOnly — the SPA needs to
    # read it to echo back in the X-Atlas-CSRF header (double-submit
    # pattern). Still Secure + SameSite=Lax so it can't leak over
    # http:// or get sent on cross-site POSTs.
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def _client_ip(request: Request) -> str | None:
    # Trust only the immediate peer in dev; a reverse-proxy-aware
    # deployment (Caddy in prod) strips X-Forwarded-For before it
    # reaches us and the direct client IP is the proxy. We record
    # whichever the framework gives us; it's metadata, not a
    # security boundary.
    client = request.client
    return client.host if client else None


def _rate_limit_identity(email: str, ip: str | None) -> str:
    """Rate-limit key that doesn't leak the email in Redis.

    Two-tuple of (short sha256 of normalized email, ip or "-").
    Keeps the window tied to the same email across IPs and to the
    same IP across a brief email-spray attempt.
    """
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
    return f"{digest}:{ip or '-'}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@auth_router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account and start a session.",
)
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> UserOut:
    settings = get_settings()
    ip = _client_ip(request)

    current, limit, retry_after = check_and_increment(
        scope="auth:register",
        identifier=ip or "-",
        limit=settings.register_max_attempts,
        window_seconds=settings.register_window_seconds,
    )
    if current > limit:
        response.headers["Retry-After"] = str(retry_after)
        raise APIError(
            code="rate_limited",
            message="Too many registration attempts. Try again later.",
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )

    user = auth_svc.register_user(
        db,
        email=str(body.email),
        password=body.password,
        display_name=body.display_name,
    )
    signed = create_session(
        user_id=user.id, ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(
        response, signed_session=signed, csrf=generate_csrf_token(),
    )
    return UserOut.model_validate(user)


@auth_router.post(
    "/login",
    response_model=UserOut,
    summary="Verify credentials and start a session.",
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> UserOut:
    settings = get_settings()
    ip = _client_ip(request)
    rl_id = _rate_limit_identity(str(body.email), ip)

    current, limit, retry_after = check_and_increment(
        scope="auth:login",
        identifier=rl_id,
        limit=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
    )
    if current > limit:
        response.headers["Retry-After"] = str(retry_after)
        raise APIError(
            code="rate_limited",
            message="Too many login attempts. Try again later.",
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )

    user = auth_svc.authenticate(db, email=str(body.email), password=body.password)
    if user is None:
        # Uniform 401 for both "no such user" and "wrong password"
        # — the service's dummy_verify ensures latency matches.
        raise APIError(
            code="invalid_credentials",
            message="Invalid email or password.",
            status_code=401,
        )

    reset(scope="auth:login", identifier=rl_id)

    signed = create_session(
        user_id=user.id, ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(
        response, signed_session=signed, csrf=generate_csrf_token(),
    )
    return UserOut.model_validate(user)


@auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session.",
)
def logout(
    request: Request,
    response: Response,
) -> None:
    settings = get_settings()
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        resolved = read_session(cookie)
        if resolved is not None:
            raw_id, _ = resolved
            destroy_session(raw_id)
    _clear_session_cookies(response)


@auth_router.get(
    "/me",
    response_model=UserOut,
    summary="Current authenticated user.",
)
def me(
    user: Annotated[User, Depends(current_user)],
) -> UserOut:
    return UserOut.model_validate(user)


@drawing_claim_router.post(
    "/{drawing_id}/claim",
    response_model=DrawingClaimOut,
    summary="Take ownership of an unclaimed drawing.",
)
def claim(
    drawing_id: UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> DrawingClaimOut:
    drawing: Drawing = auth_svc.claim_drawing(db, drawing_id, user)
    return DrawingClaimOut(
        drawing_id=drawing.id,
        owner_id=drawing.owner_id,  # type: ignore[arg-type]
    )
