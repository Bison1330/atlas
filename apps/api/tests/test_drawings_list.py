"""Tests for GET /drawings (M2-drawings-ui slice).

Covers the 4 access cases from the research doc §8.1:

- owned drawings are returned
- project-shared drawings (caller is a project member) are returned
- unclaimed (owner_id IS NULL) drawings are returned
- drawings owned by another user with no shared project are *not*
  returned — the critical isolation invariant.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Drawing, Project, ProjectMember, User
from app.main import app
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _make_drawing(
    db,
    *,
    owner_id: UUID | None,
    project_id: UUID | None = None,
    filename: str = "plan.pdf",
) -> Drawing:
    d = Drawing(
        source_filename=filename,
        source_s3_key=f"drawings/{uuid4().hex[:8]}/source.pdf",
        size_bytes=1024,
        content_hash=f"sha256:{uuid4().hex}",
        owner_id=owner_id,
        project_id=project_id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _make_other_user(db) -> User:
    u = User(
        email=f"other-{uuid4().hex[:6]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "B" * 43,
        display_name="Other",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_project(db, *, created_by: UUID, members: list[UUID]) -> Project:
    p = Project(name="Shared", created_by=created_by)
    db.add(p)
    db.flush()
    for user_id in members:
        db.add(ProjectMember(project_id=p.id, user_id=user_id))
    db.commit()
    db.refresh(p)
    return p


# ---------- empty ----------


class TestListEmpty:
    def test_no_drawings_returns_zero(self, client, db):
        r = client.get("/drawings")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0
        assert body["drawings"] == []


# ---------- owned / unclaimed ----------


class TestListOwnedAndUnclaimed:
    def test_returns_owned_drawings(self, client, db):
        _make_drawing(db, owner_id=TEST_USER_ID, filename="mine.pdf")
        r = client.get("/drawings")
        body = r.json()
        assert body["count"] == 1
        item = body["drawings"][0]
        assert item["source_filename"] == "mine.pdf"
        assert item["is_owner"] is True

    def test_returns_unclaimed_drawings(self, client, db):
        # Legacy / pre-M7 drawing with no owner.
        _make_drawing(db, owner_id=None, filename="legacy.pdf")
        r = client.get("/drawings")
        body = r.json()
        assert body["count"] == 1
        assert body["drawings"][0]["is_owner"] is False

    def test_newest_first(self, client, db):
        # Insert in out-of-order names; list should order by created_at desc.
        _make_drawing(db, owner_id=TEST_USER_ID, filename="oldest.pdf")
        _make_drawing(db, owner_id=TEST_USER_ID, filename="middle.pdf")
        _make_drawing(db, owner_id=TEST_USER_ID, filename="newest.pdf")
        r = client.get("/drawings")
        filenames = [d["source_filename"] for d in r.json()["drawings"]]
        assert filenames == ["newest.pdf", "middle.pdf", "oldest.pdf"]


# ---------- project-shared ----------


class TestListProjectShared:
    def test_project_member_sees_project_drawing(self, client, db):
        other = _make_other_user(db)
        project = _make_project(
            db, created_by=other.id,
            members=[other.id, TEST_USER_ID],  # test user is a member
        )
        d = _make_drawing(
            db, owner_id=other.id, project_id=project.id,
            filename="shared.pdf",
        )
        r = client.get("/drawings")
        body = r.json()
        assert body["count"] == 1
        item = body["drawings"][0]
        assert item["id"] == str(d.id)
        assert item["source_filename"] == "shared.pdf"
        assert item["is_owner"] is False
        assert item["project_id"] == str(project.id)

    def test_project_non_member_does_not_see_project_drawing(
        self, client, db,
    ):
        other = _make_other_user(db)
        # Project exists but TEST_USER_ID is *not* a member.
        project = _make_project(
            db, created_by=other.id, members=[other.id],
        )
        _make_drawing(
            db, owner_id=other.id, project_id=project.id,
        )
        r = client.get("/drawings")
        assert r.json()["count"] == 0


# ---------- cross-user isolation (the critical invariant) ----------


class TestCrossUserIsolation:
    def test_other_users_private_drawings_invisible(self, client, db):
        other = _make_other_user(db)
        _make_drawing(db, owner_id=other.id, filename="theirs.pdf")
        # My drawing too, to make sure the filter isn't "return nothing"
        # pathologically.
        _make_drawing(db, owner_id=TEST_USER_ID, filename="mine.pdf")
        r = client.get("/drawings")
        body = r.json()
        assert body["count"] == 1
        assert body["drawings"][0]["source_filename"] == "mine.pdf"

    def test_soft_cap_at_100(self, client, db):
        # 105 owned drawings; response caps at 100.
        for i in range(105):
            _make_drawing(
                db, owner_id=TEST_USER_ID, filename=f"plan-{i:03d}.pdf",
            )
        r = client.get("/drawings")
        body = r.json()
        assert body["count"] == 100


# ---------- auth ----------


class TestAuthGate:
    def test_anonymous_is_401(self, anon_client):
        r = anon_client.get("/drawings")
        assert r.status_code == 401
