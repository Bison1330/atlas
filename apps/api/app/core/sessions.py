"""Redis-backed session store + cookie signing helpers.

A session ID is an opaque 256-bit token handed to the client in
an ``HttpOnly + Secure + SameSite=Lax`` cookie. The server stores
``{user_id, created_at, ip_seen, ua_seen}`` in Redis under
``atlas:session:{session_id}`` with a sliding TTL.

The cookie *value* is the raw session ID signed with
:mod:`itsdangerous` using the configured
``session_secret``. Tampering flips the signature and the request
is treated as unauthenticated — no Redis lookup happens.

Why opaque IDs + Redis rather than JWT: revocation is a single
``DEL`` and TTL handles expiry without a GC job. Cheap and
well-understood.

Why sliding TTL (every authenticated request bumps the expiry):
forces re-auth only for users who were genuinely inactive, not
for users on long sessions. Matches the pattern most web apps
actually run.
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from itsdangerous import BadSignature, TimestampSigner

from app.core.config import get_settings
from app.core.redis import get_redis

log = logging.getLogger("atlas.api.sessions")

_SESSION_KEY_PREFIX = "atlas:session:"

# Cached signer — rebuilt on first use or when the secret setting
# changes (tests patch the secret; cache_clear is called explicitly
# in that path).
_signer: TimestampSigner | None = None


def _get_signer() -> TimestampSigner:
    global _signer
    if _signer is None:
        settings = get_settings()
        secret = settings.session_secret
        if not secret:
            # Dev / test: generate a per-process secret so the app
            # boots without ATLAS_SESSION_SECRET set. Warn loudly so
            # production deployments don't accidentally ship like this.
            secret = secrets.token_urlsafe(48)
            log.warning(
                "session.secret_missing_using_random_dev_key — "
                "set ATLAS_SESSION_SECRET in production.",
            )
        _signer = TimestampSigner(secret, salt="atlas.session.v1")
    return _signer


def clear_signer_cache() -> None:
    """Test helper — drop the cached signer so the next call re-reads settings."""
    global _signer
    _signer = None


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """What the session store holds per session ID.

    ``ip_seen`` / ``ua_seen`` are captured for forensic purposes
    only — we *don't* invalidate the session on IP/UA change (too
    many false positives for users on mobile networks). A future
    account-activity page can surface these.

    ``ttl_seconds`` is the TTL this specific session was created
    with. Stored so :func:`touch_session` can re-apply the same
    value on sliding bumps — otherwise a short demo session would
    silently extend back to the regular session TTL on its first
    authenticated request. Legacy records (no field) fall back to
    ``settings.session_ttl_seconds``.
    """

    user_id: UUID
    created_at: datetime
    ip_seen: str | None
    ua_seen: str | None
    ttl_seconds: int | None = None


def _encode(record: SessionRecord) -> str:
    return json.dumps({
        "user_id": str(record.user_id),
        "created_at": record.created_at.isoformat(),
        "ip_seen": record.ip_seen,
        "ua_seen": record.ua_seen,
        "ttl_seconds": record.ttl_seconds,
    })


def _decode(raw: bytes | str) -> SessionRecord | None:
    try:
        data: dict[str, Any] = json.loads(raw)
        return SessionRecord(
            user_id=UUID(data["user_id"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            ip_seen=data.get("ip_seen"),
            ua_seen=data.get("ua_seen"),
            ttl_seconds=data.get("ttl_seconds"),
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _create_session_with_ttl(
    *,
    user_id: UUID,
    ip: str | None,
    user_agent: str | None,
    ttl_seconds: int,
) -> str:
    """Private helper — the two public constructors wrap this.

    Kept separate so :func:`create_session` and
    :func:`create_demo_session` stay single-purpose: callers can't
    accidentally pass a short demo TTL to the regular login flow by
    supplying a wrong keyword argument, because there is no such
    argument to pass.
    """
    raw_id = secrets.token_urlsafe(32)
    record = SessionRecord(
        user_id=user_id,
        created_at=datetime.now(UTC),
        ip_seen=ip,
        ua_seen=user_agent,
        ttl_seconds=ttl_seconds,
    )
    get_redis().setex(
        _SESSION_KEY_PREFIX + raw_id,
        ttl_seconds,
        _encode(record),
    )
    return _get_signer().sign(raw_id).decode("utf-8")


def create_session(
    *, user_id: UUID, ip: str | None, user_agent: str | None,
) -> str:
    """Create a new session for a fully-authenticated real user.

    Uses ``settings.session_ttl_seconds`` — the standard multi-day
    sliding TTL. For the shared demo account use
    :func:`create_demo_session` instead; the two are deliberately
    separate so the shorter demo TTL can't leak into the regular
    login path.
    """
    return _create_session_with_ttl(
        user_id=user_id,
        ip=ip,
        user_agent=user_agent,
        ttl_seconds=get_settings().session_ttl_seconds,
    )


def create_demo_session(
    *, user_id: UUID, ip: str | None, user_agent: str | None,
) -> str:
    """Create a new session for the shared demo account.

    Uses ``settings.demo_session_ttl_seconds`` (24 h by default)
    instead of the standard session TTL. The per-session TTL is
    stored on the :class:`SessionRecord` so that sliding bumps via
    :func:`touch_session` re-apply the same short TTL — otherwise
    the first authenticated request after demo-login would extend
    the session back to the multi-day default.
    """
    return _create_session_with_ttl(
        user_id=user_id,
        ip=ip,
        user_agent=user_agent,
        ttl_seconds=get_settings().demo_session_ttl_seconds,
    )


def read_session(signed_cookie_value: str) -> tuple[str, SessionRecord] | None:
    """Validate the signed cookie, look the session up in Redis.

    Returns ``(raw_id, record)`` on hit. Returns ``None`` when:

    - signature is invalid,
    - cookie is older than ``session_ttl_seconds`` (timestamp
      check on the signer — defence-in-depth in case Redis
      TTL doesn't fire),
    - Redis has no matching key,
    - stored payload is unparseable.
    """
    if not signed_cookie_value:
        return None
    settings = get_settings()
    try:
        raw_id_bytes = _get_signer().unsign(
            signed_cookie_value.encode("utf-8"),
            max_age=settings.session_ttl_seconds,
        )
    except BadSignature:
        return None
    raw_id = raw_id_bytes.decode("utf-8")
    raw = get_redis().get(_SESSION_KEY_PREFIX + raw_id)
    if raw is None:
        return None
    record = _decode(raw)
    if record is None:
        return None
    return raw_id, record


def touch_session(raw_id: str) -> None:
    """Sliding-TTL bump — call on every authenticated request.

    Reads the per-session TTL stamped on the record at creation
    time so a demo session keeps its short TTL on every bump.
    Legacy records without the field fall back to the global
    default.
    """
    settings = get_settings()
    ttl_seconds: int | None = None
    raw = get_redis().get(_SESSION_KEY_PREFIX + raw_id)
    if raw is not None:
        record = _decode(raw)
        if record is not None and record.ttl_seconds is not None:
            ttl_seconds = record.ttl_seconds
    effective_ttl = ttl_seconds if ttl_seconds is not None else settings.session_ttl_seconds
    get_redis().expire(_SESSION_KEY_PREFIX + raw_id, effective_ttl)


def destroy_session(raw_id: str) -> None:
    """Delete one session (logout)."""
    get_redis().delete(_SESSION_KEY_PREFIX + raw_id)


# ---------------------------------------------------------------------------
# CSRF helpers
# ---------------------------------------------------------------------------


def generate_csrf_token() -> str:
    """New random CSRF token for the double-submit pattern.

    Returned on login/register so the client can echo it on every
    mutating request. Validation happens at the middleware or
    route-dependency layer: require the ``X-Atlas-CSRF`` header to
    equal the value in the ``atlas_csrf`` cookie.
    """
    return secrets.token_urlsafe(32)
