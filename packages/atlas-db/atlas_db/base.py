"""Declarative base + mixins shared by every ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root of the SQLAlchemy declarative hierarchy."""


class TimestampMixin:
    """Provides ``created_at`` and ``updated_at`` managed by Postgres.

    ``updated_at`` uses SQLAlchemy's ``onupdate`` which fires on ORM
    updates only. For M1 every mutation goes through the ORM, so this
    is sufficient; if we ever introduce raw SQL updates we should
    promote this to a Postgres trigger.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
