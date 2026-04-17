"""projects, project_members, drawings.project_id, annotations.author_user_id

M8 — thin collaboration slice. Adds two tables and extends two
existing tables:

- ``projects``: the shared workspace primitive. ``created_by`` is
  RESTRICTed so a creator can't be deleted while their projects
  still exist — M8.2 handles transfer/delete flows.
- ``project_members``: flat membership (no role column in v1 —
  D-15). Composite PK on (project_id, user_id). Dropped if the
  project is deleted; RESTRICTed on the user side so deleting a
  user requires explicit membership cleanup first.
- ``drawings.project_id``: nullable FK; SET NULL on project
  delete. NULL = personal drawing, owner-only (M7 semantics).
- ``annotations.author_user_id``: nullable FK; SET NULL on user
  delete (keeps the note readable, drops the link). Pre-M8 rows
  get NULL — no backfill.

Revision ID: 0006_projects
Revises: 0005_users_and_owner_id
Create Date: 2026-04-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_projects"
down_revision: str | None = "0005_users_and_owner_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_projects_created_by",
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120",
            name="ck_projects_name_len",
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) BETWEEN 1 AND 2000",
            name="ck_projects_description_len",
        ),
    )
    op.create_index("ix_projects_created_by", "projects", ["created_by"])

    op.create_table(
        "project_members",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name="fk_project_members_project_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_project_members_user_id",
        ),
    )
    op.create_index(
        "ix_project_members_user_id", "project_members", ["user_id"],
    )

    op.add_column(
        "drawings",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_drawings_project_id",
        "drawings",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_drawings_project_id", "drawings", ["project_id"])

    op.add_column(
        "annotations",
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_annotations_author_user_id",
        "annotations",
        "users",
        ["author_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_annotations_author_user_id", "annotations", ["author_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_annotations_author_user_id", table_name="annotations",
    )
    op.drop_constraint(
        "fk_annotations_author_user_id", "annotations", type_="foreignkey",
    )
    op.drop_column("annotations", "author_user_id")

    op.drop_index("ix_drawings_project_id", table_name="drawings")
    op.drop_constraint(
        "fk_drawings_project_id", "drawings", type_="foreignkey",
    )
    op.drop_column("drawings", "project_id")

    op.drop_index("ix_project_members_user_id", table_name="project_members")
    op.drop_table("project_members")

    op.drop_index("ix_projects_created_by", table_name="projects")
    op.drop_table("projects")
