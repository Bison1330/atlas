"""users.is_demo flag.

Marks the shared demo/prospect account used by the one-click
"Try the demo" login. Enforced by ``/auth/demo-login``: the
endpoint requires both ``is_demo=true`` on the target user and
a match against a hardcoded email allow-list in the route. The
flag also drives a client-side "shared demo data" banner.

Revision ID: 0007_users_is_demo
Revises: 0006_projects
Create Date: 2026-04-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_users_is_demo"
down_revision: str | None = "0006_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_demo")
