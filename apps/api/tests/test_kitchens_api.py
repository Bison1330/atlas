"""Tests for /app/kitchens — the V1 kitchen intake endpoints (S1).

Wires the real routes, real DB, real Redis (via the auto-flushing
fixture in ``conftest.py``) to a :class:`FakeKitchenIntake` via the
``_get_kitchen_intake`` dependency override. No Anthropic calls.

Coverage:
  * happy path — intake progresses turn-by-turn, fields accumulate,
    brief flips complete on the scripted final turn.
  * pushback — the intake service returns text without an
    ``update_brief`` call, mimicking Atlas gently refusing an
    impossible request.
  * resume — persist after one turn, load state fresh, continue.
  * auth — a second user gets 404 (not 403) on another user's
    project, matching the membership-based 404-on-not-yours policy.
  * rate limit — 61st message inside the window returns 429 with a
    Retry-After header.
"""

from __future__ import annotations

from typing import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.auth_dep import current_user
from app.main import app
from app.routes.kitchens import _get_kitchen_intake
from app.services.kitchen_intake import (
    FakeKitchenIntake,
    IntakeTurnResult,
    KitchenIntake,
)
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def with_intake():
    """Install a scripted :class:`FakeKitchenIntake` via override.

    Returns the installed instance so tests can inspect the turns
    Atlas saw (e.g. to assert the conversation history was passed
    correctly).
    """
    installed: dict[str, FakeKitchenIntake] = {}

    def _apply(scripted: list[IntakeTurnResult]) -> FakeKitchenIntake:
        fake = FakeKitchenIntake(scripted)
        app.dependency_overrides[_get_kitchen_intake] = lambda: fake
        installed["fake"] = fake
        return fake

    yield _apply
    app.dependency_overrides.pop(_get_kitchen_intake, None)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_start_creates_project_and_first_turn(self, client, with_intake, db):
        with_intake([
            IntakeTurnResult(
                assistant_message=(
                    "Got it — a colonial kitchen opening up to the "
                    "living room. How many people usually cook?"
                ),
                field_updates={
                    "scope_type": "remodel",
                    "must_have_features": ["island", "open concept"],
                },
            ),
        ])

        r = client.post(
            "/app/kitchens",
            json={
                "project_type": "kitchen_remodel",
                "initial_message": (
                    "I want to redo my 1980s colonial kitchen and "
                    "open it up to the living room with an island."
                ),
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["project"]["project_type"] == "kitchen_remodel"
        assert body["project"]["lifecycle_state"] == "brief_drafting"
        assert body["brief"]["status"] == "drafting"
        assert body["extracted_fields"]["scope_type"] == "remodel"
        assert body["extracted_fields"]["must_have_features"] == [
            "island", "open concept",
        ]
        assert body["is_complete"] is False
        assert "colonial" in body["atlas_response"].lower()

    def test_progressive_intake_ends_with_complete(
        self, client, with_intake, db,
    ):
        fake = with_intake([
            # Turn 1 (response to the initial message).
            IntakeTurnResult(
                assistant_message=(
                    "Nice — a 1980s colonial opening up. What's the "
                    "rough footprint of the current kitchen?"
                ),
                field_updates={
                    "scope_type": "remodel",
                    "must_have_features": ["island"],
                    "style_direction": "transitional",
                },
            ),
            # Turn 2.
            IntakeTurnResult(
                assistant_message=(
                    "10x14 gives us room for a proper island. "
                    "What's your budget feel like?"
                ),
                field_updates={
                    "approximate_dimensions": {"width_ft": 10, "length_ft": 14},
                },
            ),
            # Turn 3.
            IntakeTurnResult(
                assistant_message=(
                    "$60–80k is workable for this scope. Which "
                    "appliances matter most to you?"
                ),
                field_updates={
                    "budget_range": {"low_usd": 60000, "high_usd": 80000},
                    "primary_purpose": "family_daily_cooking",
                },
            ),
            # Turn 4.
            IntakeTurnResult(
                assistant_message=(
                    "Got it — gas range, big fridge. And what "
                    "city are you in? I'll factor in local code."
                ),
                field_updates={
                    "appliance_priorities": ["gas range", "large fridge"],
                },
            ),
            # Turn 5 — final.
            IntakeTurnResult(
                assistant_message=(
                    "I have everything I need to design your kitchen. "
                    "Let me put together three options."
                ),
                field_updates={
                    "location_address_or_zip": "94110",
                    "timeline": "flexible",
                    "hoa_or_historic_district": "no",
                    "accessibility_needs": "none",
                    "kitchen_layout_goal": "island",
                    "existing_features_to_keep": "hardwood floors",
                    "existing_features_to_change": "cabinets, layout",
                    "load_bearing_walls_known": "unsure",
                    "plumbing_locations_known": "approximate",
                    "dealbreakers": [],
                },
                is_complete=True,
                completion_summary={
                    "scope_type": "remodel",
                    "layout": "island",
                    "budget_range": {"low_usd": 60000, "high_usd": 80000},
                    "style_direction": "transitional",
                },
            ),
        ])

        # Start.
        r = client.post(
            "/app/kitchens",
            json={
                "project_type": "kitchen_remodel",
                "initial_message": "I want to redo my colonial kitchen.",
            },
        )
        assert r.status_code == 201, r.text
        project_id = r.json()["project"]["id"]
        assert r.json()["is_complete"] is False

        # Turns 2–5.
        for user_msg in [
            "It's about 10 by 14.",
            "We're thinking $60–80k if that's workable.",
            "Gas range and a big fridge are the priorities.",
            "We're in 94110, no HOA.",
        ]:
            r = client.post(
                f"/app/kitchens/{project_id}/messages",
                json={"content": user_msg},
            )
            assert r.status_code == 200, r.text

        body = r.json()
        assert body["is_complete"] is True
        assert body["extracted_fields"]["_completion_summary"]["layout"] == "island"

        # Fetch the detail view and confirm message ordering.
        r = client.get(f"/app/kitchens/{project_id}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["is_complete"] is True
        # 5 user + 5 assistant = 10 messages.
        roles = [m["role"] for m in d["messages"]]
        assert roles == [
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
        ]
        # Fake saw the full history on the last call.
        assert len(fake.recorded_turns[-1]) == 9  # 5 user + 4 assistant turns so far

    def test_opus_failure_rolls_back_project_and_brief(self, db):
        """If the first Opus call raises, no rows are committed.

        Catches the "orphan empty project on startup failure" class
        of bug. Uses ``raise_server_exceptions=False`` so the
        TestClient returns 500 instead of re-raising into the test,
        matching what a real client would see — and lets us assert
        on both the HTTP status and the DB state in one shot.
        """
        from fastapi.testclient import TestClient

        from app.db import KitchenBrief as KBModel
        from app.db import Project as ProjectModel

        class RaisingIntake:
            def send_turn(self, messages):
                raise RuntimeError(
                    "anthropic transient 502 (simulated)"
                )

        app.dependency_overrides[_get_kitchen_intake] = RaisingIntake
        try:
            with TestClient(app, raise_server_exceptions=False) as tclient:
                r = tclient.post(
                    "/app/kitchens",
                    json={
                        "project_type": "kitchen_remodel",
                        "initial_message": "remodel please",
                    },
                )
            assert r.status_code == 500, r.text
        finally:
            app.dependency_overrides.pop(_get_kitchen_intake, None)

        # Neither a Project nor a Brief was committed.
        from sqlalchemy import func as sa_func
        from sqlalchemy import select

        project_count = db.execute(
            select(sa_func.count()).select_from(ProjectModel)
            .where(ProjectModel.created_by == TEST_USER_ID)
        ).scalar_one()
        brief_count = db.execute(
            select(sa_func.count()).select_from(KBModel)
        ).scalar_one()
        assert project_count == 0, (
            f"expected zero projects after rollback, got {project_count}"
        )
        assert brief_count == 0, (
            f"expected zero briefs after rollback, got {brief_count}"
        )

    def test_message_after_complete_returns_409(self, client, with_intake, db):
        with_intake([
            IntakeTurnResult(
                assistant_message="Ready to design.",
                field_updates={},
                is_complete=True,
                completion_summary={"scope_type": "remodel"},
            ),
        ])
        r = client.post(
            "/app/kitchens",
            json={
                "project_type": "kitchen_remodel",
                "initial_message": "quick one: my kitchen is toast",
            },
        )
        assert r.status_code == 201
        project_id = r.json()["project"]["id"]

        r2 = client.post(
            f"/app/kitchens/{project_id}/messages",
            json={"content": "actually one more question"},
        )
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "brief_complete"


# ---------------------------------------------------------------------------
# Pushback: Atlas declines to extract impossible values
# ---------------------------------------------------------------------------


class TestImpossibleRequestPushback:
    def test_pushback_turn_does_not_populate_fields(
        self, client, with_intake, db,
    ):
        """If the model sends text only (no update_brief call) the
        brief's extracted_fields stay empty for that turn — the
        service does not fabricate values."""
        with_intake([
            IntakeTurnResult(
                assistant_message=(
                    "Quick reality check — a 20-foot island won't "
                    "fit in a 10-foot kitchen; the walk space around "
                    "it wouldn't meet minimums. Want to go with the "
                    "biggest island that actually fits, or reshape "
                    "the room?"
                ),
                field_updates={},  # no extraction this turn.
            ),
        ])

        r = client.post(
            "/app/kitchens",
            json={
                "project_type": "kitchen_remodel",
                "initial_message": (
                    "I want a 20-foot island in my 10-foot kitchen."
                ),
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["extracted_fields"] == {}
        assert body["is_complete"] is False
        assert "won't fit" in body["atlas_response"].lower()


# ---------------------------------------------------------------------------
# Resume after disconnect — state survives across requests
# ---------------------------------------------------------------------------


class TestResume:
    def test_state_persists_across_requests(self, client, with_intake, db):
        with_intake([
            IntakeTurnResult(
                assistant_message="What's the rough footprint?",
                field_updates={"scope_type": "remodel"},
            ),
            IntakeTurnResult(
                assistant_message="10x14 is workable. Budget?",
                field_updates={
                    "approximate_dimensions": {"width_ft": 10, "length_ft": 14},
                },
            ),
        ])

        # Turn 1.
        r = client.post(
            "/app/kitchens",
            json={
                "project_type": "kitchen_remodel",
                "initial_message": "remodeling my kitchen",
            },
        )
        assert r.status_code == 201, r.text
        project_id = r.json()["project"]["id"]

        # Simulate the client reloading before turn 2.
        r = client.get(f"/app/kitchens/{project_id}")
        assert r.status_code == 200
        state = r.json()
        assert state["extracted_fields"] == {"scope_type": "remodel"}
        assert len(state["messages"]) == 2  # user + assistant from turn 1.

        # Turn 2.
        r = client.post(
            f"/app/kitchens/{project_id}/messages",
            json={"content": "10 by 14"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["extracted_fields"]["approximate_dimensions"] == {
            "width_ft": 10, "length_ft": 14,
        }


# ---------------------------------------------------------------------------
# Auth — cross-user access returns 404
# ---------------------------------------------------------------------------


class TestCrossUserAccess:
    def test_other_user_cannot_read_project(self, client, with_intake, db):
        from app.db import User
        from app.core.passwords import hash_password

        with_intake([
            IntakeTurnResult(
                assistant_message="got it",
                field_updates={"scope_type": "remodel"},
            ),
        ])

        # Owner (TEST_USER_ID via autoauth) starts a project.
        r = client.post(
            "/app/kitchens",
            json={
                "project_type": "kitchen_remodel",
                "initial_message": "remodel plz",
            },
        )
        assert r.status_code == 201
        project_id = r.json()["project"]["id"]

        # Spin up a second user row and swap the current_user
        # override to impersonate them.
        other = User(
            email="other@atlas.test",
            password_hash=hash_password("AtlasOther!2026"),
            display_name="Other",
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        app.dependency_overrides[current_user] = lambda: other
        try:
            r = client.get(f"/app/kitchens/{project_id}")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "not_found"
        finally:
            # Restore the auto-auth override for subsequent tests.
            from tests.conftest import TEST_USER_EMAIL

            owner = User(
                id=TEST_USER_ID,
                email=TEST_USER_EMAIL,
                password_hash="$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "B" * 43,
                display_name="Test User",
            )
            app.dependency_overrides[current_user] = lambda: owner


# ---------------------------------------------------------------------------
# Rate limit — 60/min per user per project
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_429_after_window_exhausted(self, client, with_intake, db):
        # Script 61 "happy" replies. 60 messages hit the intake
        # service; the 61st short-circuits at the rate limiter.
        # (``kitchens:starts`` and ``kitchens:intake_messages`` use
        # separate buckets, so the initial start doesn't eat into
        # the per-message budget.)
        replies = [
            IntakeTurnResult(
                assistant_message="ack",
                field_updates={},
            )
            for _ in range(61)
        ]
        with_intake(replies)

        r = client.post(
            "/app/kitchens",
            json={
                "project_type": "kitchen_remodel",
                "initial_message": "remodel",
            },
        )
        assert r.status_code == 201
        project_id = r.json()["project"]["id"]

        # 60 messages — all succeed (60th is current_count == 60,
        # which is <= limit).
        for i in range(60):
            r = client.post(
                f"/app/kitchens/{project_id}/messages",
                json={"content": f"turn {i}"},
            )
            assert r.status_code == 200, f"turn {i}: {r.text}"

        # 61st message — rate-limited before the intake runs.
        r = client.post(
            f"/app/kitchens/{project_id}/messages",
            json={"content": "one too many"},
        )
        assert r.status_code == 429
        body = r.json()
        assert body["error"]["code"] == "rate_limited"
        assert "retry_after_seconds" in body["error"]["details"]
        assert r.headers.get("Retry-After") is not None
