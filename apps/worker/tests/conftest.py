"""Test config — provide minimal env so WorkerSettings instantiates."""

from __future__ import annotations

import os

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://atlas:atlas@localhost:5432/atlas")
os.environ.setdefault("S3_BUCKET", "atlas-test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")
