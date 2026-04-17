"""element_sources, elements

M2 — structured drawings. Adds two tables:

- ``element_sources``: one row per "production run" (extraction,
  generation, or manual_override) against a drawing. Carries
  producer name + version + lifecycle.
- ``elements``: polymorphic structured-drawing elements. ``kind``
  discriminator + JSONB ``geometry``/``attrs``/``ifc_properties``.
  NCS layer fields are first-class for index-friendly classification
  queries.

Schema notes:

- ``elements`` uses a polymorphic single-table layout (D-01) — adding
  a kind is a one-line CHECK update + ``ElementKind`` enum extension.
- Geometry is JSONB now (D-02); the M3 PostGIS migration will add a
  proper ``geometry`` column and backfill from JSONB.
- ``elements.host_element_id`` is a self-FK with ``ON DELETE SET
  NULL`` — when a wall is deleted the doors hosted in it stick
  around as orphans (the alternative — cascading deletes — would
  silently lose data on a re-extraction that classifies a wall
  differently).
- All FKs to ``drawings``, ``sheets``, and ``element_sources`` cascade
  on delete so wiping a drawing removes everything.

Revision ID: 0003_elements
Revises: 0002_drawings
Create Date: 2026-04-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_elements"
down_revision: str | None = "0002_drawings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCE_KINDS = ("extraction", "generation", "manual_override")
_SOURCE_KIND_CHECK = "source_kind IN (" + ", ".join(f"'{s}'" for s in _SOURCE_KINDS) + ")"

_SOURCE_STATUSES = ("queued", "running", "completed", "failed")
_SOURCE_STATUS_CHECK = (
    "status IN (" + ", ".join(f"'{s}'" for s in _SOURCE_STATUSES) + ")"
)

_ELEMENT_KINDS = (
    "room",
    "wall",
    "door",
    "window",
    "column",
    "stair",
    "dimension",
    "annotation",
    "symbol",
    "other",
)
_ELEMENT_KIND_CHECK = "kind IN (" + ", ".join(f"'{k}'" for k in _ELEMENT_KINDS) + ")"


def upgrade() -> None:
    op.create_table(
        "element_sources",
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
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("producer_name", sa.String(128), nullable=False),
        sa.Column("producer_version", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(2048), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            ["drawing_id"],
            ["drawings.id"],
            ondelete="CASCADE",
            name="fk_element_sources_drawing_id",
        ),
        sa.CheckConstraint(_SOURCE_KIND_CHECK, name="ck_element_sources_kind_valid"),
        sa.CheckConstraint(_SOURCE_STATUS_CHECK, name="ck_element_sources_status_valid"),
    )
    op.create_index(
        "ix_element_sources_drawing_id", "element_sources", ["drawing_id"]
    )
    op.create_index("ix_element_sources_status", "element_sources", ["status"])
    op.create_index(
        "ix_element_sources_drawing_finished",
        "element_sources",
        ["drawing_id", "finished_at"],
    )

    op.create_table(
        "elements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "sheet_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("number", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_layer", sa.String(256), nullable=True),
        sa.Column("ncs_layer", sa.String(128), nullable=True),
        sa.Column("ncs_major_group", sa.String(4), nullable=True),
        sa.Column("ncs_minor_group", sa.String(8), nullable=True),
        sa.Column("ifc_type", sa.String(64), nullable=True),
        sa.Column(
            "ifc_properties",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "geometry",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "bbox",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "attrs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "host_element_id",
            postgresql.UUID(as_uuid=True),
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
        sa.ForeignKeyConstraint(
            ["sheet_id"],
            ["sheets.id"],
            ondelete="CASCADE",
            name="fk_elements_sheet_id",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["element_sources.id"],
            ondelete="CASCADE",
            name="fk_elements_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["host_element_id"],
            ["elements.id"],
            ondelete="SET NULL",
            name="fk_elements_host_element_id",
        ),
        sa.CheckConstraint(_ELEMENT_KIND_CHECK, name="ck_elements_kind_valid"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_elements_confidence_range",
        ),
    )
    op.create_index("ix_elements_sheet_id", "elements", ["sheet_id"])
    op.create_index("ix_elements_source_id", "elements", ["source_id"])
    op.create_index("ix_elements_sheet_kind", "elements", ["sheet_id", "kind"])
    op.create_index(
        "ix_elements_ncs_major_group", "elements", ["ncs_major_group"]
    )
    op.create_index(
        "ix_elements_host_element_id", "elements", ["host_element_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_elements_host_element_id", table_name="elements")
    op.drop_index("ix_elements_ncs_major_group", table_name="elements")
    op.drop_index("ix_elements_sheet_kind", table_name="elements")
    op.drop_index("ix_elements_source_id", table_name="elements")
    op.drop_index("ix_elements_sheet_id", table_name="elements")
    op.drop_table("elements")

    op.drop_index(
        "ix_element_sources_drawing_finished", table_name="element_sources"
    )
    op.drop_index("ix_element_sources_status", table_name="element_sources")
    op.drop_index("ix_element_sources_drawing_id", table_name="element_sources")
    op.drop_table("element_sources")
