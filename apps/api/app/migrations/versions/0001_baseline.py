"""baseline

Atlas M0 baseline migration. No tables yet — this marker establishes the
alembic versioning starting point so future migrations have a parent.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-16

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
