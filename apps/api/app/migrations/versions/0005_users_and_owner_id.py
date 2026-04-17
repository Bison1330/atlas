"""users, owner_id on drawings

M7 — basic authentication. Adds one table + one column + one index:

- ``users``: local accounts authenticated by email + argon2id
  password hash. ``email_verified`` column present but the
  verification flow lives in M7.1.
- ``drawings.owner_id``: nullable FK to ``users.id`` (D-13).
  Drawings uploaded before M7 keep NULL owner and are
  "unclaimed" until a user claims them via
  ``POST /drawings/{id}/claim``. New uploads post-M7 must carry
  an owner.

FK policy: ``RESTRICT`` on the users → drawings relationship so a
user can't be deleted while they still own drawings. No cascade
(we don't want "delete account" to silently wipe data; a proper
account-deletion flow ships in a later milestone).

Revision ID: 0005_users_and_owner_id
Revises: 0004_annotations
Create Date: 2026-04-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_users_and_owner_id"
down_revision: str | None = "0004_annotations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "char_length(email) BETWEEN 3 AND 255",
            name="ck_users_email_len",
        ),
        sa.CheckConstraint(
            "char_length(password_hash) BETWEEN 10 AND 512",
            name="ck_users_password_hash_len",
        ),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.add_column(
        "drawings",
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_drawings_owner_id",
        "drawings",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_drawings_owner_id", "drawings", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_drawings_owner_id", table_name="drawings")
    op.drop_constraint("fk_drawings_owner_id", "drawings", type_="foreignkey")
    op.drop_column("drawings", "owner_id")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
