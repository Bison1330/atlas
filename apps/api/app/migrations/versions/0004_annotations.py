"""annotations

M6 — thin review slice. Adds one table:

- ``annotations``: user-authored notes attached to a specific
  extracted element. No auth yet, so ``author_name`` is a free-
  form text field; M7 auth lands an ``author_id`` FK and either
  demotes this or drops it.

FK policy matches the research doc (docs/research/m6-annotations.md):

- ``drawing_id`` cascades on delete — removing a drawing wipes
  every annotation scoped to it.
- ``element_id`` restricts — an annotation's target must exist
  for the row to exist. Under the immutable-source model a
  re-extraction creates *new* element IDs instead of deleting old
  ones, so RESTRICT should never fire in practice; if it does,
  something upstream violated an invariant and the loud failure
  is preferable to silent data loss.

Indexes:

- ``(drawing_id, created_at)`` for the "all annotations on this
  drawing, newest first" list view.
- ``(element_id)`` for the element-scoped endpoint.

Revision ID: 0004_annotations
Revises: 0003_elements
Create Date: 2026-04-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_annotations"
down_revision: str | None = "0003_elements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "drawing_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "element_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("author_name", sa.String(120), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
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
            ["drawing_id"],
            ["drawings.id"],
            ondelete="CASCADE",
            name="fk_annotations_drawing_id",
        ),
        sa.ForeignKeyConstraint(
            ["element_id"],
            ["elements.id"],
            ondelete="RESTRICT",
            name="fk_annotations_element_id",
        ),
        sa.CheckConstraint(
            "char_length(author_name) BETWEEN 1 AND 120",
            name="ck_annotations_author_name_len",
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4000",
            name="ck_annotations_body_len",
        ),
    )
    op.create_index(
        "ix_annotations_drawing_created",
        "annotations",
        ["drawing_id", "created_at"],
    )
    op.create_index(
        "ix_annotations_element_id",
        "annotations",
        ["element_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_annotations_element_id", table_name="annotations")
    op.drop_index("ix_annotations_drawing_created", table_name="annotations")
    op.drop_table("annotations")
