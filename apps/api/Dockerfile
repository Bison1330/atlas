# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install atlas-core first (shared package) so its layer caches
COPY packages/atlas-core /packages/atlas-core
RUN pip install /packages/atlas-core

# Then API deps
COPY apps/api/pyproject.toml /app/pyproject.toml
RUN pip install \
      "fastapi>=0.115,<1" \
      "uvicorn[standard]>=0.32,<1" \
      "pydantic>=2.9,<3" \
      "pydantic-settings>=2.5,<3" \
      "sqlalchemy>=2.0.35,<3" \
      "psycopg[binary,pool]>=3.2,<4" \
      "alembic>=1.13,<2" \
      "redis>=5.1,<6" \
      "rq>=1.16,<2" \
      "structlog>=24.4,<26" \
      "sentry-sdk[fastapi]>=2.17,<3" \
      "boto3>=1.35,<2"

COPY apps/api /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
