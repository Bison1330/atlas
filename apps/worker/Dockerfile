# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY packages/atlas-core /packages/atlas-core
RUN pip install /packages/atlas-core

COPY apps/worker/pyproject.toml /app/pyproject.toml
RUN pip install \
      "rq>=1.16,<2" \
      "redis>=5.1,<6" \
      "structlog>=24.4,<26" \
      "sentry-sdk>=2.17,<3" \
      "pydantic>=2.9,<3" \
      "pydantic-settings>=2.5,<3"

COPY apps/worker /app

CMD ["python", "-m", "worker.main"]
