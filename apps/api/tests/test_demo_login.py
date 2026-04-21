"""Tests for ``POST /auth/demo-login`` — the one-click prospect bypass.

Every test uses ``anon_client`` so the ``_auto_auth`` override from
conftest is bypassed and the real cookie / rate-limit / lookup
plumbing runs end-to-end. Each test that needs the demo user seeds
it directly against the ``db`` fixture, matching the pattern the
seed script uses in production.

The tests intentionally exercise the *authorization surface* more
than the happy path, because the endpoint's value is in its
restrictiveness: it grants a session with no password, so each
fence that's supposed to keep non-demo accounts out needs a test.
"""

from __future__ import annotations

import logging
from unittest.mock import ANY

import pytest

from app.core.config import get_settings
from app.core.passwords import hash_password
from app.core.sessions import read_session
from app.db import User
from app.routes.auth import DEMO_LOGIN_ALLOWED_EMAILS

DEMO_EMAIL = "demo@atlas.build"
_SETTINGS = get_settings()
DEMO_SESSION_TTL_SECONDS = _SETTINGS.demo_session_ttl_seconds
DEMO_LOGIN_MAX_PER_HOUR = _SETTINGS.demo_login_max_per_hour


def _seed_demo_user(
    db, *, email: str = DEMO_EMAIL, is_demo: bool = True, is_active: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password("AtlasDemo!2026"),
        display_name="Atlas Demo",
        is_active=is_active,
        is_demo=is_demo,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestDemoLoginSuccess:
    def test_grants_session_for_seeded_demo_user(self, anon_client, db):
        _seed_demo_user(db)
        r = anon_client.post("/auth/demo-login")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == DEMO_EMAIL
        assert body["is_demo"] is True
        assert body["is_active"] is True
        # Cookies land so subsequent requests are authenticated.
        assert "atlas_session" in anon_client.cookies
        assert "atlas_csrf" in anon_client.cookies

    def test_subsequent_me_reports_is_demo(self, anon_client, db):
        _seed_demo_user(db)
        anon_client.post("/auth/demo-login")
        r = anon_client.get("/auth/me")
        assert r.status_code == 200
        assert r.json()["is_demo"] is True

    def test_empty_body_is_accepted(self, anon_client, db):
        _seed_demo_user(db)
        # No payload — there's no user-controlled field, so the
        # endpoint must work with a bare POST.
        r = anon_client.post("/auth/demo-login", json={})
        assert r.status_code == 200

    def test_two_clients_can_demo_in_parallel(self, anon_client, db):
        # The demo account is a shared identity — multiple browsers
        # logging in at once should each get their own session.
        _seed_demo_user(db)
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as second:
            r1 = anon_client.post("/auth/demo-login")
            r2 = second.post("/auth/demo-login")
            assert r1.status_code == 200
            assert r2.status_code == 200
            s1 = anon_client.cookies.get("atlas_session")
            s2 = second.cookies.get("atlas_session")
            assert s1 and s2 and s1 != s2


class TestDemoLoginSessionShape:
    def test_session_ttl_is_short(self, anon_client, db):
        """Demo sessions are capped at 24h rather than the normal multi-day TTL."""
        from app.core import redis as redis_mod
        _seed_demo_user(db)
        anon_client.post("/auth/demo-login")

        signed = anon_client.cookies.get("atlas_session")
        assert signed is not None
        resolved = read_session(signed)
        assert resolved is not None
        raw_id, record = resolved
        # The stored record carries the demo TTL so sliding bumps
        # don't accidentally elevate it to the default.
        assert record.ttl_seconds == DEMO_SESSION_TTL_SECONDS
        # Redis key TTL is within ±30s of the demo window. The
        # ``expires_at`` that matters to a downstream consumer is
        # ``now + ttl``; this assertion is that form restated in
        # TTL terms (and is what the spec calls out as the tight
        # bound on drift between session creation and observation).
        ttl = redis_mod.get_redis().ttl(f"atlas:session:{raw_id}")
        assert abs(ttl - DEMO_SESSION_TTL_SECONDS) < 30, (
            f"demo session TTL {ttl}s is more than 30s off the expected "
            f"{DEMO_SESSION_TTL_SECONDS}s"
        )

    def test_cookie_max_age_matches_demo_ttl(self, anon_client, db):
        _seed_demo_user(db)
        r = anon_client.post("/auth/demo-login")
        # Set-Cookie max-age should reflect the 24h cap — not the
        # global default. Both the session and CSRF cookies carry it.
        set_cookies = r.headers.get_list("set-cookie")
        assert any(
            f"Max-Age={DEMO_SESSION_TTL_SECONDS}" in c
            for c in set_cookies
        ), set_cookies


class TestDemoLoginAuthorizationFences:
    def test_no_demo_user_is_403(self, anon_client):
        # Nothing seeded — the allow-listed email doesn't exist.
        r = anon_client.post("/auth/demo-login")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "demo_login_not_available"

    def test_user_exists_but_is_demo_false_is_403(self, anon_client, db):
        # Flag flipped off — seeding with ``is_demo=False`` should
        # still deny even though the email matches the allow-list.
        _seed_demo_user(db, is_demo=False)
        r = anon_client.post("/auth/demo-login")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "demo_login_not_available"

    def test_user_is_demo_true_but_inactive_is_403(self, anon_client, db):
        _seed_demo_user(db, is_active=False)
        r = anon_client.post("/auth/demo-login")
        assert r.status_code == 403

    def test_other_account_with_is_demo_true_is_403(self, anon_client, db):
        # Defence-in-depth: even if a non-allow-listed account has
        # is_demo flipped to true, the endpoint must refuse it.
        # With only "demo@atlas.build" in the allow-list, any other
        # email gets rejected at the lookup step (no matching row).
        _seed_demo_user(db, email="sneaky@atlas.build", is_demo=True)
        r = anon_client.post("/auth/demo-login")
        assert r.status_code == 403

    def test_allowed_email_set_is_the_guard(self):
        # Contract check: if someone ever widens the allow-list they
        # need to revisit these tests intentionally.
        assert DEMO_LOGIN_ALLOWED_EMAILS == frozenset({DEMO_EMAIL})


class TestDemoLoginSpoofAttempts:
    """The endpoint must ignore any caller-supplied email — body,
    query, or header. The target user is resolved from the hardcoded
    allow-list only. These tests assert that even when a non-demo
    account *also* exists, the server still returns the demo row.
    """

    def _seed_pair(self, db):
        demo = _seed_demo_user(db)
        # A real (non-demo) user whose email an attacker might try to
        # inject. is_demo=False by construction — if the endpoint ever
        # honoured the injected email, we'd see 200 for this account.
        other = User(
            email="s26@example.com",
            password_hash=hash_password("correcthorsebatterystaple"),
            display_name="Regular Account",
            is_active=True,
            is_demo=False,
            email_verified=True,
        )
        db.add(other)
        db.commit()
        return demo, other

    def test_body_email_is_ignored(self, anon_client, db):
        _, _ = self._seed_pair(db)
        r = anon_client.post(
            "/auth/demo-login", json={"email": "s26@example.com"},
        )
        # 200, demo user returned — not 200 for the other account, and
        # not 403 (we don't care that the body was "invalid").
        assert r.status_code == 200, r.text
        assert r.json()["email"] == DEMO_EMAIL
        assert r.json()["is_demo"] is True

    def test_query_email_is_ignored(self, anon_client, db):
        _, _ = self._seed_pair(db)
        r = anon_client.post("/auth/demo-login?email=s26@example.com")
        assert r.status_code == 200, r.text
        assert r.json()["email"] == DEMO_EMAIL

    def test_header_injection_is_ignored(self, anon_client, db):
        _, _ = self._seed_pair(db)
        # Nothing reads X-User-Email today; assert that stays true.
        r = anon_client.post(
            "/auth/demo-login",
            headers={"X-User-Email": "s26@example.com"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["email"] == DEMO_EMAIL


class TestDemoLoginAuditLog:
    def test_success_is_logged_at_info(self, anon_client, db, caplog):
        _seed_demo_user(db)
        with caplog.at_level(logging.INFO, logger="atlas.api.auth"):
            r = anon_client.post(
                "/auth/demo-login",
                headers={"User-Agent": "pytest-ua/1.0"},
            )
        assert r.status_code == 200
        records = [
            rec for rec in caplog.records
            if rec.name == "atlas.api.auth" and rec.message == "auth.demo_login"
        ]
        # Exactly one audit row — the endpoint emits one event per call.
        assert len(records) == 1, [rec.__dict__ for rec in caplog.records]
        rec = records[0]
        assert rec.levelno == logging.INFO
        assert getattr(rec, "outcome", None) == "success"
        assert getattr(rec, "user_agent", None) == "pytest-ua/1.0"
        # Session token never logged.
        assert "atlas_session" not in rec.getMessage()
        for attr in vars(rec).values():
            assert "atlas_session" not in str(attr)

    def test_forbidden_is_logged_at_info(self, anon_client, caplog):
        # No user seeded → 403. Should still leave an INFO audit row.
        with caplog.at_level(logging.INFO, logger="atlas.api.auth"):
            r = anon_client.post("/auth/demo-login")
        assert r.status_code == 403
        records = [
            rec for rec in caplog.records
            if rec.name == "atlas.api.auth" and rec.message == "auth.demo_login"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.INFO
        assert getattr(records[0], "outcome", None) == "forbidden"


class TestDemoLoginRateLimit:
    def test_rate_limit_triggers_429_after_configured_max(self, anon_client, db):
        from app.core import redis as redis_mod
        redis_mod.get_redis().flushdb()
        _seed_demo_user(db)

        # Burn through the full allowance — each hit is a success
        # (200) since the user exists — then the next one is 429.
        for _ in range(DEMO_LOGIN_MAX_PER_HOUR):
            r = anon_client.post("/auth/demo-login")
            assert r.status_code == 200
        r = anon_client.post("/auth/demo-login")
        assert r.status_code == 429
        body = r.json()
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["details"]["retry_after_seconds"] > 0
        # Spec: Retry-After header must be present on the 429.
        retry_after_hdr = r.headers.get("retry-after")
        assert retry_after_hdr is not None, list(r.headers.keys())
        assert int(retry_after_hdr) > 0

    def test_rate_limit_counts_failed_attempts_too(self, anon_client, db):
        # No seeded user: every hit is a 403 but should still count
        # against the IP-scoped bucket. Otherwise an attacker could
        # probe the endpoint indefinitely.
        from app.core import redis as redis_mod
        redis_mod.get_redis().flushdb()
        for _ in range(DEMO_LOGIN_MAX_PER_HOUR):
            r = anon_client.post("/auth/demo-login")
            assert r.status_code == 403
        r = anon_client.post("/auth/demo-login")
        assert r.status_code == 429


class TestSeedIdempotency:
    """The seed helper script (``scripts/seed_demo_account.py``) claims
    idempotency. That script isn't imported here (it lives outside the
    api package), but we re-use its primitives to exercise the same
    invariants: re-running must not duplicate the demo user row and
    must normalize the flag if it was off.
    """

    def test_re_running_does_not_duplicate_user(self, db):
        from sqlalchemy import select
        first = _seed_demo_user(db)
        # Simulate "script re-run": look up existing, ensure flag set,
        # don't insert another.
        existing = db.execute(
            select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        existing.is_demo = True
        db.add(existing)
        db.commit()

        rows = db.execute(
            select(User).where(User.email == DEMO_EMAIL)
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == first.id

    def test_rerun_reflips_flag_if_cleared(self, db):
        from sqlalchemy import select
        user = _seed_demo_user(db, is_demo=False)
        assert user.is_demo is False
        # Mimic the script's "if not is_demo: flip and commit" branch.
        existing = db.execute(
            select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        if not existing.is_demo:
            existing.is_demo = True
            db.add(existing)
            db.commit()
        db.refresh(existing)
        assert existing.is_demo is True


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    # Explicit per-test Redis wipe for the demo bucket — the conftest
    # ``_redis_clean`` fixture already runs, but this makes intent
    # obvious for anyone extending these tests.
    from app.core import redis as redis_mod
    try:
        redis_mod.get_redis().flushdb()
    except Exception:
        pass
    yield
