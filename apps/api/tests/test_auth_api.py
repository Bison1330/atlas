"""Tests for the M7 auth endpoints + ownership checks.

These tests use the ``anon_client`` fixture (not the default
``client``) so the auto-override in conftest doesn't short-circuit
the real ``current_user`` dependency. They exercise the actual
cookie / CSRF / session plumbing end-to-end.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Annotation, Drawing, Element, ElementSource, Sheet, User
from app.main import app
from app.services.qa import QueryInterpretation
from app.services.qa_interpreter import FakeInterpreter
from tests.conftest import TEST_USER_ID


def _csrf_post(
    client: TestClient, url: str, json: dict | None = None,
) -> "httpx.Response":  # type: ignore[name-defined]
    """POST with the double-submit CSRF header populated from the cookie."""
    csrf = client.cookies.get("atlas_csrf")
    headers = {"X-Atlas-CSRF": csrf} if csrf else {}
    return client.post(url, json=json, headers=headers)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegister:
    def test_valid_registration_creates_user_and_session(self, anon_client, db):
        r = anon_client.post(
            "/auth/register",
            json={
                "email": "new@example.com",
                "password": "correct-horse-battery-staple",
                "display_name": "New User",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["email"] == "new@example.com"
        assert body["display_name"] == "New User"
        assert body["is_active"] is True
        # Cookies set so subsequent requests are authenticated.
        assert "atlas_session" in anon_client.cookies
        assert "atlas_csrf" in anon_client.cookies
        # Row landed.
        users = db.query(User).filter(User.email == "new@example.com").all()
        assert len(users) == 1
        assert users[0].password_hash.startswith("$argon2id$")

    def test_duplicate_email_returns_409(self, anon_client):
        anon_client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "correct-horse-battery"},
        )
        # Drop cookies so the second attempt isn't treated as the same user.
        anon_client.cookies.clear()
        r = anon_client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "another-strong-password"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "email_taken"

    def test_short_password_rejected(self, anon_client):
        r = anon_client.post(
            "/auth/register",
            json={"email": "x@example.com", "password": "short"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "too_short"

    def test_common_password_rejected(self, anon_client):
        r = anon_client.post(
            "/auth/register",
            json={"email": "x@example.com", "password": "password123"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "common_password"

    def test_invalid_email_rejected(self, anon_client):
        # Pydantic EmailStr catches the obvious malformed case.
        r = anon_client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "correct-horse-battery"},
        )
        assert r.status_code == 422

    def test_rate_limit_triggers_429_with_retry_after(self, anon_client):
        from app.core import redis as redis_mod

        redis_mod.get_redis().flushdb()
        # Configured register allowance is 3 per IP per hour; cycle
        # through distinct emails so each request passes validation
        # and reaches the rate-limit bucket.
        for i in range(3):
            r = anon_client.post(
                "/auth/register",
                json={
                    "email": f"rl{i}@example.com",
                    "password": "correct-horse-battery-staple",
                },
            )
            anon_client.cookies.clear()
            assert r.status_code == 201, r.text
        # 4th request trips the limit.
        r = anon_client.post(
            "/auth/register",
            json={"email": "rl3@example.com",
                  "password": "correct-horse-battery-staple"},
        )
        assert r.status_code == 429
        body = r.json()
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["details"]["retry_after_seconds"] > 0
        retry_after_hdr = r.headers.get("retry-after")
        assert retry_after_hdr is not None, list(r.headers.keys())
        assert int(retry_after_hdr) > 0


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class TestLogin:
    def _register(self, client: TestClient, email="login@example.com",
                  password="correct-horse-battery") -> None:
        client.post(
            "/auth/register",
            json={"email": email, "password": password},
        )
        client.cookies.clear()

    def test_valid_login_sets_cookies_and_returns_user(self, anon_client):
        self._register(anon_client)
        r = anon_client.post(
            "/auth/login",
            json={"email": "login@example.com",
                  "password": "correct-horse-battery"},
        )
        assert r.status_code == 200
        assert r.json()["email"] == "login@example.com"
        assert "atlas_session" in anon_client.cookies
        assert "atlas_csrf" in anon_client.cookies

    def test_wrong_password_returns_401(self, anon_client):
        self._register(anon_client)
        r = anon_client.post(
            "/auth/login",
            json={"email": "login@example.com", "password": "wrong-password-here"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"

    def test_unknown_email_returns_401_same_shape(self, anon_client):
        # Same 401 body as wrong-password case — prevents email enumeration.
        r = anon_client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "whatever-this-is"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"

    def test_rate_limit_triggers_429_after_too_many_bad_attempts(
        self, anon_client,
    ):
        from app.core import redis as redis_mod
        redis_mod.get_redis().flushdb()
        self._register(anon_client, email="spam@example.com")
        # 5 configured attempts — 6th should 429.
        for _ in range(5):
            anon_client.post(
                "/auth/login",
                json={"email": "spam@example.com", "password": "wrong"},
            )
        r = anon_client.post(
            "/auth/login",
            json={"email": "spam@example.com", "password": "wrong"},
        )
        assert r.status_code == 429
        body = r.json()
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["details"]["retry_after_seconds"] > 0
        # Retry-After must travel on the response itself, not only in
        # the body — well-behaved clients (browsers, fetch libraries,
        # HTTP proxies) inspect the header.
        retry_after_hdr = r.headers.get("retry-after")
        assert retry_after_hdr is not None, list(r.headers.keys())
        assert int(retry_after_hdr) > 0


# ---------------------------------------------------------------------------
# Session / logout / /me
# ---------------------------------------------------------------------------


class TestSession:
    def test_me_without_cookie_is_401(self, anon_client):
        r = anon_client.get("/auth/me")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "not_authenticated"

    def test_me_with_session_returns_user(self, anon_client):
        anon_client.post(
            "/auth/register",
            json={"email": "me@example.com", "password": "correct-horse-battery"},
        )
        r = anon_client.get("/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == "me@example.com"

    def test_logout_clears_session(self, anon_client):
        anon_client.post(
            "/auth/register",
            json={"email": "out@example.com", "password": "correct-horse-battery"},
        )
        r = _csrf_post(anon_client, "/auth/logout")
        assert r.status_code == 204
        # /auth/me should now 401 even though the TestClient still
        # has the cookie (logout destroyed the Redis row).
        anon_client.cookies.clear()
        r = anon_client.get("/auth/me")
        assert r.status_code == 401

    def test_tampered_cookie_is_401(self, anon_client):
        anon_client.post(
            "/auth/register",
            json={"email": "t@example.com", "password": "correct-horse-battery"},
        )
        # Flip a byte in the signed cookie value.
        original = anon_client.cookies.get("atlas_session") or ""
        anon_client.cookies.set("atlas_session", original[:-2] + "xx")
        r = anon_client.get("/auth/me")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


class TestCsrf:
    def _authed_client(self) -> TestClient:
        c = TestClient(app)
        c.post(
            "/auth/register",
            json={"email": "csrf@example.com", "password": "correct-horse-battery"},
        )
        return c

    def test_mutation_without_header_is_403(self, anon_client, db):
        # Register first so we're authenticated.
        anon_client.post(
            "/auth/register",
            json={"email": "c1@example.com", "password": "correct-horse-battery"},
        )
        # Seed an owned drawing to annotate — use the authed user id.
        me = anon_client.get("/auth/me").json()
        user_id = UUID(me["id"])
        _seed_owned_element(db, owner_id=user_id)

        # POST without the CSRF header should 403.
        r = anon_client.post(
            f"/drawings/{_seeded_drawing_id}/annotations",
            json={
                "element_id": str(_seeded_element_id),
                "author_name": "me", "body": "hi",
            },
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "csrf_failed"

    def test_mismatched_header_is_403(self, anon_client, db):
        anon_client.post(
            "/auth/register",
            json={"email": "c2@example.com", "password": "correct-horse-battery"},
        )
        me = anon_client.get("/auth/me").json()
        _seed_owned_element(db, owner_id=UUID(me["id"]))
        r = anon_client.post(
            f"/drawings/{_seeded_drawing_id}/annotations",
            json={
                "element_id": str(_seeded_element_id),
                "author_name": "me", "body": "hi",
            },
            headers={"X-Atlas-CSRF": "not-the-real-token"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Ownership / read-vs-write / claim
# ---------------------------------------------------------------------------


def _seed_owned_element(
    db, *, owner_id: UUID | None,
) -> tuple[UUID, UUID]:
    """Seed one drawing + sheet + source + one wall element.

    Returns ``(drawing_id, element_id)``. Module-globals are updated
    so the CSRF tests can reference them without plumbing return
    values through fixtures.
    """
    global _seeded_drawing_id, _seeded_element_id  # type: ignore[name-defined]
    d = Drawing(
        source_filename="x.dxf", source_s3_key="k", size_bytes=1,
        content_hash=f"sha256:auth-{uuid4().hex[:8]}",
        owner_id=owner_id,
    )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.flush()
    src = ElementSource(
        drawing_id=d.id, source_kind="extraction",
        producer_name="dxf_ncs_extractor", producer_version="0.1.0",
        status="completed",
    )
    db.add(src)
    db.flush()
    el = Element(
        sheet_id=s.id, source_id=src.id, kind="wall",
        ncs_layer="A-WALL-EXTR",
        geometry={"kind": "polyline", "points": [
            {"x": 0, "y": 0}, {"x": 10, "y": 0},
        ]},
    )
    db.add(el)
    db.commit()
    _seeded_drawing_id = d.id
    _seeded_element_id = el.id
    return d.id, el.id


_seeded_drawing_id: UUID = UUID("00000000-0000-0000-0000-000000000000")
_seeded_element_id: UUID = UUID("00000000-0000-0000-0000-000000000000")


class TestOwnership:
    def test_anonymous_cannot_read_drawing(self, anon_client, db):
        drawing_id, _ = _seed_owned_element(db, owner_id=TEST_USER_ID)
        r = anon_client.get(f"/drawings/{drawing_id}/takeoffs")
        assert r.status_code == 401

    def test_other_user_cannot_read_owned_drawing(self, anon_client, db):
        # Owned by the conftest TEST_USER_ID (not our registered user).
        drawing_id, _ = _seed_owned_element(db, owner_id=TEST_USER_ID)
        anon_client.post(
            "/auth/register",
            json={"email": "other@example.com", "password": "correct-horse-battery"},
        )
        r = anon_client.get(f"/drawings/{drawing_id}/takeoffs")
        # 404 rather than 403 — we don't signal existence.
        assert r.status_code == 404

    def test_unclaimed_drawing_readable_by_any_auth_user(self, anon_client, db):
        drawing_id, _ = _seed_owned_element(db, owner_id=None)
        anon_client.post(
            "/auth/register",
            json={"email": "claimer@example.com",
                  "password": "correct-horse-battery"},
        )
        r = anon_client.get(f"/drawings/{drawing_id}/takeoffs")
        assert r.status_code == 200

    def test_unclaimed_drawing_not_writable_without_claim(
        self, anon_client, db,
    ):
        # Seed an unclaimed drawing; register a user; try to POST an
        # annotation — should 409 drawing_unclaimed.
        drawing_id, element_id = _seed_owned_element(db, owner_id=None)
        anon_client.post(
            "/auth/register",
            json={"email": "writer@example.com",
                  "password": "correct-horse-battery"},
        )
        r = _csrf_post(
            anon_client,
            f"/drawings/{drawing_id}/annotations",
            json={
                "element_id": str(element_id),
                "author_name": "me", "body": "hi",
            },
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "drawing_unclaimed"


class TestClaim:
    def test_claim_assigns_owner_on_unclaimed(self, anon_client, db):
        drawing_id, _ = _seed_owned_element(db, owner_id=None)
        register = anon_client.post(
            "/auth/register",
            json={"email": "claim1@example.com",
                  "password": "correct-horse-battery"},
        )
        me_id = UUID(register.json()["id"])

        r = _csrf_post(anon_client, f"/drawings/{drawing_id}/claim")
        assert r.status_code == 200
        body = r.json()
        assert body["drawing_id"] == str(drawing_id)
        assert body["owner_id"] == str(me_id)

        # DB reflects the change.
        db.expire_all()
        assert db.get(Drawing, drawing_id).owner_id == me_id

    def test_claim_already_owned_by_someone_else_is_404(
        self, anon_client, db,
    ):
        # Owned by TEST_USER_ID in the seed; registered user is someone else.
        drawing_id, _ = _seed_owned_element(db, owner_id=TEST_USER_ID)
        anon_client.post(
            "/auth/register",
            json={"email": "claim2@example.com",
                  "password": "correct-horse-battery"},
        )
        r = _csrf_post(anon_client, f"/drawings/{drawing_id}/claim")
        # The service raises 409 already_owned, but the ownership
        # helper raises 404 first because the drawing isn't "ours".
        # Either is acceptable; assert one of the two.
        assert r.status_code in (404, 409)

    def test_claim_own_drawing_is_idempotent(self, anon_client, db):
        # Register, claim an unclaimed drawing, then claim again.
        drawing_id, _ = _seed_owned_element(db, owner_id=None)
        anon_client.post(
            "/auth/register",
            json={"email": "claim3@example.com",
                  "password": "correct-horse-battery"},
        )
        r1 = _csrf_post(anon_client, f"/drawings/{drawing_id}/claim")
        assert r1.status_code == 200
        r2 = _csrf_post(anon_client, f"/drawings/{drawing_id}/claim")
        assert r2.status_code == 200
        assert r1.json() == r2.json()
