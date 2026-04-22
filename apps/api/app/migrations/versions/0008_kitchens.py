"""V1 kitchen design system — intake schema.

Adds the two tables that hold the kitchen-project intake conversation
and the structured brief the intake LLM builds up turn-by-turn, plus
two nullable columns on ``projects`` that distinguish a kitchen
project from an M8-era "group of drawings" project.

Schema shape matches ``docs/v1-kitchen-architecture.md`` §2. The
``superseded_by`` self-FK on ``kitchen_briefs`` supports the
refinement-versioning decision (new row per refinement, old chained
via this column) even though S9 is still weeks away.

Revision ID: 0008_kitchens
Revises: 0007_users_is_demo
Create Date: 2026-04-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_kitchens"
down_revision: str | None = "0007_users_is_demo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BRIEF_STATUSES = "'drafting', 'complete', 'superseded'"
_BRIEF_ROLES = "'user', 'assistant', 'system'"
_PROJECT_TYPES = (
    "'kitchen_remodel','kitchen_new','bathroom',"
    "'retail_fitout','small_office','addition','other'"
)
_LIFECYCLE_STATES = (
    "'brief_drafting','brief_complete','generating','designing',"
    "'priced','quoted','archived'"
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # projects: new columns for v1 kitchen pivot.
    # ------------------------------------------------------------------
    op.add_column(
        "projects",
        sa.Column("project_type", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "lifecycle_state",
            sa.String(length=30),
            nullable=True,
            server_default="brief_drafting",
        ),
    )
    op.create_check_constraint(
        "ck_projects_project_type",
        "projects",
        f"project_type IS NULL OR project_type IN ({_PROJECT_TYPES})",
    )
    op.create_check_constraint(
        "ck_projects_lifecycle_state",
        "projects",
        f"lifecycle_state IS NULL OR lifecycle_state IN ({_LIFECYCLE_STATES})",
    )

    # ------------------------------------------------------------------
    # kitchen_briefs
    # ------------------------------------------------------------------
    op.create_table(
        "kitchen_briefs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="drafting",
        ),
        sa.Column(
            "superseded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("kitchen_briefs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "extracted_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"status IN ({_BRIEF_STATUSES})",
            name="ck_kitchen_briefs_status",
        ),
    )
    op.create_index(
        "ix_kitchen_briefs_project_id", "kitchen_briefs", ["project_id"],
    )
    op.create_index(
        "ix_kitchen_briefs_status", "kitchen_briefs", ["status"],
    )

    # ------------------------------------------------------------------
    # kitchen_brief_messages
    # ------------------------------------------------------------------
    op.create_table(
        "kitchen_brief_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("kitchen_briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "extracted_delta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"role IN ({_BRIEF_ROLES})",
            name="ck_kitchen_brief_messages_role",
        ),
    )
    op.create_index(
        "ix_kitchen_brief_messages_brief_id",
        "kitchen_brief_messages",
        ["brief_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_kitchen_brief_messages_brief_id",
        table_name="kitchen_brief_messages",
    )
    op.drop_table("kitchen_brief_messages")

    op.drop_index("ix_kitchen_briefs_status", table_name="kitchen_briefs")
    op.drop_index("ix_kitchen_briefs_project_id", table_name="kitchen_briefs")
    op.drop_table("kitchen_briefs")

    op.drop_constraint(
        "ck_projects_lifecycle_state", "projects", type_="check",
    )
    op.drop_constraint(
        "ck_projects_project_type", "projects", type_="check",
    )
    op.drop_column("projects", "lifecycle_state")
    op.drop_column("projects", "project_type")
