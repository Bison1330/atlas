"""Integration tests for the M8 projects + membership + drawing
assignment endpoints.

Uses the ``anon_client`` fixture because the scenarios exercise two
distinct users (we register-and-login a second user in each test
via helpers), so the per-test autoauth override in conftest would
short-circuit the multi-user check.

Authorship / annotation-integration tests piggyback on the auth'd
``client`` fixture where a single-user flow is enough.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import (
    Annotation,
    Drawing,
    Element,
    ElementSource,
    Project,
    ProjectMember,
    Sheet,
    User,
)
from app.main import app
from tests.conftest import TEST_USER_ID


# ---------- helpers ----------


def _register_and_login(
    anon_client: TestClient, email: str, password: str = "correct-horse-battery",
) -> dict:
    """Register a user and return the /me body. TestClient keeps cookies."""
    r = anon_client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": email.split("@")[0]},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _csrf_post(client: TestClient, url: str, json=None):
    csrf = client.cookies.get("atlas_csrf")
    return client.post(url, json=json, headers={"X-Atlas-CSRF": csrf or ""})


def _csrf_patch(client: TestClient, url: str, json=None):
    csrf = client.cookies.get("atlas_csrf")
    return client.patch(url, json=json, headers={"X-Atlas-CSRF": csrf or ""})


def _csrf_delete(client: TestClient, url: str):
    csrf = client.cookies.get("atlas_csrf")
    return client.delete(url, headers={"X-Atlas-CSRF": csrf or ""})


def _seed_owned_drawing_with_element(
    db, *, owner_id: UUID,
) -> tuple[UUID, UUID]:
    d = Drawing(
        source_filename="x.dxf", source_s3_key="k", size_bytes=1,
        content_hash=f"sha256:proj-{uuid4().hex[:8]}",
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
        status="completed", finished_at=datetime.now(UTC),
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
    return d.id, el.id


# ---------- Project CRUD ----------


class TestProjectCrud:
    def test_create_project_auto_adds_creator_as_member(self, anon_client, db):
        me = _register_and_login(anon_client, "creator@example.com")
        r = _csrf_post(
            anon_client, "/projects",
            json={"name": "Hillside House", "description": "2024 residential"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Hillside House"
        assert body["created_by"] == me["id"]
        assert body["member_count"] == 1
        assert body["members"][0]["user_id"] == me["id"]
        # Flat-membership warning surfaces so the UI can render it.
        assert body["warnings"]["flat_membership"] is True

    def test_list_projects_only_shows_my_memberships(self, anon_client, db):
        _register_and_login(anon_client, "owner@example.com")
        _csrf_post(
            anon_client, "/projects",
            json={"name": "Mine", "description": None},
        )
        # Log out + register a second user; list should be empty.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        _register_and_login(anon_client, "other@example.com")
        r = anon_client.get("/projects")
        assert r.status_code == 200
        assert r.json()["projects"] == []

    def test_get_project_as_non_member_is_404(self, anon_client, db):
        # User A creates a project.
        _register_and_login(anon_client, "a@example.com")
        created = _csrf_post(
            anon_client, "/projects",
            json={"name": "A's Project", "description": None},
        ).json()
        # Log out, register B, try to read A's project.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        _register_and_login(anon_client, "b@example.com")
        r = anon_client.get(f"/projects/{created['id']}")
        assert r.status_code == 404

    def test_patch_project_by_member(self, anon_client):
        _register_and_login(anon_client, "p@example.com")
        created = _csrf_post(
            anon_client, "/projects",
            json={"name": "Old Name", "description": None},
        ).json()
        r = _csrf_patch(
            anon_client, f"/projects/{created['id']}",
            json={"name": "New Name"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "New Name"


# ---------- Membership ----------


class TestMembership:
    def test_add_member_by_email(self, anon_client, db):
        # User A creates project.
        a = _register_and_login(anon_client, "a-mem@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "Shared", "description": None},
        ).json()
        # User B registers (in a different TestClient cookie jar to
        # avoid losing A's session — but we'll reuse by logging out).
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        _register_and_login(anon_client, "b-mem@example.com")
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        # A logs back in to add B.
        anon_client.post(
            "/auth/login",
            json={"email": "a-mem@example.com", "password": "correct-horse-battery"},
        )
        r = _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "b-mem@example.com"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["email"] == "b-mem@example.com"

    def test_add_member_unknown_email_is_404(self, anon_client):
        _register_and_login(anon_client, "solo@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "Solo", "description": None},
        ).json()
        r = _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "nobody@example.com"},
        )
        assert r.status_code == 404

    def test_add_member_requires_existing_membership_of_caller(
        self, anon_client, db,
    ):
        # A creates project. B isn't a member. B tries to add someone.
        _register_and_login(anon_client, "ac@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "Closed", "description": None},
        ).json()
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        _register_and_login(anon_client, "bc@example.com")
        r = _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "ac@example.com"},
        )
        # Non-member sees the project as 404 — which also blocks
        # member-add.
        assert r.status_code == 404

    def test_add_same_member_twice_is_409(self, anon_client, db):
        _register_and_login(anon_client, "once@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "Dup", "description": None},
        ).json()
        # Register a target.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        _register_and_login(anon_client, "twice@example.com")
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        anon_client.post(
            "/auth/login",
            json={"email": "once@example.com", "password": "correct-horse-battery"},
        )
        r1 = _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "twice@example.com"},
        )
        assert r1.status_code == 201
        r2 = _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "twice@example.com"},
        )
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "already_member"

    def test_remove_member(self, anon_client, db):
        _register_and_login(anon_client, "keeper@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "K", "description": None},
        ).json()
        # Register a second user + log keeper back in.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        bye = _register_and_login(anon_client, "bye@example.com")
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        anon_client.post(
            "/auth/login",
            json={"email": "keeper@example.com", "password": "correct-horse-battery"},
        )
        _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "bye@example.com"},
        )
        r = _csrf_delete(
            anon_client, f"/projects/{project['id']}/members/{bye['id']}",
        )
        assert r.status_code == 204
        # Re-reading the project now shows only 1 member.
        detail = anon_client.get(f"/projects/{project['id']}").json()
        assert detail["member_count"] == 1


# ---------- Drawing assignment ----------


class TestDrawingAssignment:
    def test_owner_assigns_drawing_to_project_then_member_reads(
        self, anon_client, db,
    ):
        # Register user A, create project, seed an owned drawing.
        a = _register_and_login(anon_client, "own@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "PA", "description": None},
        ).json()
        drawing_id, _ = _seed_owned_drawing_with_element(
            db, owner_id=UUID(a["id"]),
        )
        # Assign drawing to project.
        r = _csrf_patch(
            anon_client, f"/drawings/{drawing_id}/project",
            json={"project_id": project["id"]},
        )
        assert r.status_code == 200
        assert r.json()["project_id"] == project["id"]

        # Register user B and add them to the project.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        b = _register_and_login(anon_client, "member@example.com")
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        anon_client.post(
            "/auth/login",
            json={"email": "own@example.com", "password": "correct-horse-battery"},
        )
        _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "member@example.com"},
        )

        # Log in as B and read takeoffs — should 200 now.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        anon_client.post(
            "/auth/login",
            json={"email": "member@example.com", "password": "correct-horse-battery"},
        )
        r = anon_client.get(f"/drawings/{drawing_id}/takeoffs")
        assert r.status_code == 200

    def test_non_owner_cannot_assign_drawing(self, anon_client, db):
        a = _register_and_login(anon_client, "own2@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "PB", "description": None},
        ).json()
        drawing_id, _ = _seed_owned_drawing_with_element(
            db, owner_id=UUID(a["id"]),
        )
        # B tries to reassign A's drawing.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        _register_and_login(anon_client, "attacker@example.com")
        r = _csrf_patch(
            anon_client, f"/drawings/{drawing_id}/project",
            json={"project_id": project["id"]},
        )
        # 404 — caller doesn't own it.
        assert r.status_code == 404

    def test_assign_to_project_you_are_not_member_of_is_403(
        self, anon_client, db,
    ):
        a = _register_and_login(anon_client, "own3@example.com")
        # A creates a project.
        project_a = _csrf_post(
            anon_client, "/projects",
            json={"name": "A-proj", "description": None},
        ).json()
        # A has an owned drawing.
        drawing_id, _ = _seed_owned_drawing_with_element(
            db, owner_id=UUID(a["id"]),
        )
        # B registers and creates their own project.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        _register_and_login(anon_client, "own4@example.com")
        b_project = _csrf_post(
            anon_client, "/projects",
            json={"name": "B-proj", "description": None},
        ).json()
        # A logs back in and tries to move their drawing into B's project.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        anon_client.post(
            "/auth/login",
            json={"email": "own3@example.com", "password": "correct-horse-battery"},
        )
        r = _csrf_patch(
            anon_client, f"/drawings/{drawing_id}/project",
            json={"project_id": b_project["id"]},
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "not_project_member"

    def test_unassign_drawing(self, anon_client, db):
        a = _register_and_login(anon_client, "un@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "UN", "description": None},
        ).json()
        drawing_id, _ = _seed_owned_drawing_with_element(
            db, owner_id=UUID(a["id"]),
        )
        _csrf_patch(
            anon_client, f"/drawings/{drawing_id}/project",
            json={"project_id": project["id"]},
        )
        r = _csrf_patch(
            anon_client, f"/drawings/{drawing_id}/project",
            json={"project_id": None},
        )
        assert r.status_code == 200
        assert r.json()["project_id"] is None


# ---------- Cross-member collaboration ----------


class TestCollaboration:
    def test_project_member_can_annotate_owner_drawing(self, anon_client, db):
        # Owner A seeds drawing, puts it in project, adds B.
        a = _register_and_login(anon_client, "coll-a@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "Collab", "description": None},
        ).json()
        drawing_id, element_id = _seed_owned_drawing_with_element(
            db, owner_id=UUID(a["id"]),
        )
        _csrf_patch(
            anon_client, f"/drawings/{drawing_id}/project",
            json={"project_id": project["id"]},
        )
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        b = _register_and_login(anon_client, "coll-b@example.com")
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        anon_client.post(
            "/auth/login",
            json={"email": "coll-a@example.com", "password": "correct-horse-battery"},
        )
        _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "coll-b@example.com"},
        )
        # B logs in and annotates.
        _csrf_post(anon_client, "/auth/logout")
        anon_client.cookies.clear()
        anon_client.post(
            "/auth/login",
            json={"email": "coll-b@example.com", "password": "correct-horse-battery"},
        )
        r = _csrf_post(
            anon_client, f"/drawings/{drawing_id}/annotations",
            json={
                "element_id": str(element_id),
                "body": "flagged by B",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["author_user_id"] == b["id"]
        # author_name defaulted to display_name from /auth/register.
        assert body["author_name"] == "coll-b"


# ---------- Annotation author attribution ----------


class TestAnnotationAuthorship:
    def test_author_user_id_set_on_new_annotation(self, anon_client, db):
        me = _register_and_login(anon_client, "writer@example.com")
        drawing_id, element_id = _seed_owned_drawing_with_element(
            db, owner_id=UUID(me["id"]),
        )
        r = _csrf_post(
            anon_client, f"/drawings/{drawing_id}/annotations",
            json={"element_id": str(element_id), "body": "hi"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["author_user_id"] == me["id"]
        # Display name came from registration.
        assert body["author_name"] == "writer"

    def test_legacy_annotation_has_null_author_user_id(self, anon_client, db):
        me = _register_and_login(anon_client, "legacy@example.com")
        drawing_id, element_id = _seed_owned_drawing_with_element(
            db, owner_id=UUID(me["id"]),
        )
        # Insert an annotation directly with no author_user_id (simulates pre-M8).
        db.add(Annotation(
            drawing_id=drawing_id,
            element_id=element_id,
            author_name="pre-M8 user",
            body="old note",
        ))
        db.commit()
        r = anon_client.get(f"/drawings/{drawing_id}/annotations")
        assert r.status_code == 200
        legacy = next(
            a for a in r.json()["annotations"] if a["author_name"] == "pre-M8 user"
        )
        assert legacy["author_user_id"] is None


# ---------- Rate limiting the member-add endpoint ----------


class TestAddMemberRateLimit:
    def test_add_member_429_after_burst(self, anon_client, db):
        from app.core import redis as redis_mod
        redis_mod.get_redis().flushdb()
        _register_and_login(anon_client, "rl@example.com")
        project = _csrf_post(
            anon_client, "/projects",
            json={"name": "RL", "description": None},
        ).json()
        # 10 adds per (project, ip) per minute — 11th should 429.
        for i in range(10):
            _csrf_post(
                anon_client, f"/projects/{project['id']}/members",
                json={"email": f"nope-{i}@example.com"},
            )
        r = _csrf_post(
            anon_client, f"/projects/{project['id']}/members",
            json={"email": "nope-final@example.com"},
        )
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "rate_limited"
