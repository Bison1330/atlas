"""Redis-backed sliding-window rate limiter.

Two behaviors in one tiny module:

- :func:`check_and_increment` — atomically bump a counter keyed by
  ``(scope, identifier)`` and return ``(current, limit, retry_after)``.
  When ``current > limit`` the caller raises 429.
- :func:`reset` — explicit clear (used after a successful login so
  a legitimate user isn't locked out for 15 min after one typo).

Window shape: classic counter-plus-TTL. Not a true sliding window
(we don't track individual timestamps) — it's a fixed 15-minute
bucket that resets when empty. Good enough for login / register
abuse; upgrade to log-based sliding when needed.
"""

from __future__ import annotations

from app.core.redis import get_redis


def check_and_increment(
    *, scope: str, identifier: str, limit: int, window_seconds: int,
) -> tuple[int, int, int]:
    """Atomically increment a counter, return usage metrics.

    Returns ``(current, limit, retry_after_seconds)``. When
    ``current > limit`` the caller should 429 with ``Retry-After:
    {retry_after_seconds}``.

    Pipelined so the INCR + EXPIRE happen together. EXPIRE is
    safe to call repeatedly — it just refreshes the TTL each hit,
    which means a user who keeps hitting the endpoint stays
    capped until they stop for ``window_seconds``. That's the
    intended "give up if you're being abused" behavior.
    """
    key = f"atlas:rl:{scope}:{identifier}"
    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds)
    pipe.ttl(key)
    current, _, ttl = pipe.execute()
    return int(current), limit, int(ttl) if ttl and ttl > 0 else window_seconds


def reset(*, scope: str, identifier: str) -> None:
    """Clear the counter — call on successful auth so a user who
    typoed once isn't locked out for the full window."""
    get_redis().delete(f"atlas:rl:{scope}:{identifier}")
