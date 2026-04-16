# atlas-db

Shared SQLAlchemy ORM for Atlas.

Owns the three ingest tables — `drawings`, `sheets`, `tiles` — plus the common `Base` and `TimestampMixin`. Both `apps/api` and `apps/worker` depend on this package so the schema definition has a single source of truth.

Alembic migrations continue to live in `apps/api/app/migrations/` — the API remains the owner of the migration history.
