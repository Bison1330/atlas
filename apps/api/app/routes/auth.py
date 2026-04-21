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
import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth_dep import current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import check_and_increment, reset
from app.core.sessions import (
    create_demo_session,
    create_session,
    destroy_session,
    generate_csrf_token,
    read_session,
)
from app.db import Drawing, User
from app.schemas.errors import APIError
from app.services import auth as auth_svc

log = logging.getLogger("atlas.api.auth")

# Hardcoded allow-list of email addresses permitted to use the
# ``/auth/demo-login`` bypass. This is intentionally *not* read from
# the DB: even if a malicious actor manages to flip ``is_demo=true``
# on another account, the email check here still has to match for
# the endpoint to grant a session. Belt-and-suspenders.
#
# The TTL / rate-limit numerics intentionally live in ``Settings``
# (see ``config.py``) so ops can tune them without a code change;
# only the allow-list stays in code.
DEMO_LOGIN_ALLOWED_EMAILS: frozenset[str] = frozenset({"demo@atlas.build"})

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
    is_demo: bool = False
    last_login_at: datetime | None = None


class DrawingClaimOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID
    owner_id: UUID


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _set_session_cookies(
    response: Response,
    *,
    signed_session: str,
    csrf: str,
    max_age_seconds: int | None = None,
) -> None:
    settings = get_settings()
    secure = settings.is_production
    effective_max_age = (
        max_age_seconds if max_age_seconds is not None else settings.session_ttl_seconds
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=signed_session,
        max_age=effective_max_age,
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
        max_age=effective_max_age,
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
    "/demo-login",
    response_model=UserOut,
    summary="Start a session for the shared demo account (no password).",
)
def demo_login(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> UserOut:
    """One-click sign-in for the shared demo/prospect account.

    **Authorization is deliberately layered** — any one of these
    checks failing is a 403 with error code
    ``demo_login_not_available``:

    1. Rate limit: ``demo_login_max_per_hour`` per IP.
    2. The target user row must have ``is_demo=True``.
    3. The target user's email must appear in the hardcoded
       :data:`DEMO_LOGIN_ALLOWED_EMAILS` set in this module.
    4. The account must be ``is_active``.

    The request body is intentionally ignored: there's no user-
    supplied field (body / query / header) the caller could tamper
    with to widen the blast radius to another account.

    Session TTL is capped at ``demo_session_ttl_seconds`` so demo
    sessions don't linger at the normal multi-day length.

    Every attempt logs one ``auth.demo_login`` INFO event with an
    ``outcome`` field (``success`` / ``forbidden`` / ``rate_limited``)
    so production logs can show demo usage and abuse at a glance.
    The session token is never logged.
    """
    settings = get_settings()
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent")

    current, limit, retry_after = check_and_increment(
        scope="auth:demo_login",
        identifier=ip or "-",
        limit=settings.demo_login_max_per_hour,
        window_seconds=settings.demo_login_window_seconds,
    )
    if current > limit:
        log.info(
            "auth.demo_login",
            extra={
                "outcome": "rate_limited",
                "ip": ip,
                "user_agent": user_agent,
                "retry_after_seconds": retry_after,
            },
        )
        # ``Retry-After`` MUST travel on the 429 response itself.
        # Setting ``response.headers[...]`` here is a no-op — the
        # global ``APIError`` handler builds its own ``JSONResponse``
        # and only the headers passed through the exception survive.
        raise APIError(
            code="rate_limited",
            message="Too many demo login attempts. Try again later.",
            status_code=429,
            details={"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    # Resolve the single allow-listed demo user. The loop is a no-op
    # for now (single email) but keeps the structure correct if we
    # ever add a second demo account.
    user: User | None = None
    for email in DEMO_LOGIN_ALLOWED_EMAILS:
        candidate = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if candidate is not None:
            user = candidate
            break

    # Uniform 403 for missing user / flag flipped / deactivated /
    # email off-list — don't leak which of the four failed.
    denied_reason: str | None = None
    if user is None:
        denied_reason = "no_user"
    elif not user.is_demo:
        denied_reason = "not_demo"
    elif not user.is_active:
        denied_reason = "inactive"
    elif user.email not in DEMO_LOGIN_ALLOWED_EMAILS:
        denied_reason = "email_off_list"

    if denied_reason is not None:
        log.info(
            "auth.demo_login",
            extra={
                "outcome": "forbidden",
                "reason": denied_reason,
                "ip": ip,
                "user_agent": user_agent,
            },
        )
        raise APIError(
            code="demo_login_not_available",
            message="Demo access is not available.",
            status_code=403,
        )

    assert user is not None  # narrowed by denied_reason above

    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.commit()

    signed = create_demo_session(
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )
    _set_session_cookies(
        response,
        signed_session=signed,
        csrf=generate_csrf_token(),
        max_age_seconds=settings.demo_session_ttl_seconds,
    )
    log.info(
        "auth.demo_login",
        extra={
            "outcome": "success",
            "ip": ip,
            "user_agent": user_agent,
            "user_id": str(user.id),
            "email": user.email,
        },
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
