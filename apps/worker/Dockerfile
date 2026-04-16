# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# poppler-utils is required by pdf2image for PDF rasterization.
# Other apt deps cover Pillow's optional backends (jpeg, webp, zlib).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        libjpeg62-turbo \
        libwebp7 \
        zlib1g \
        libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/atlas-core /packages/atlas-core
RUN pip install /packages/atlas-core
COPY packages/atlas-db /packages/atlas-db
RUN pip install /packages/atlas-db

COPY apps/worker/pyproject.toml /app/pyproject.toml
RUN pip install \
      "rq>=1.16,<2" \
      "redis>=5.1,<6" \
      "structlog>=24.4,<26" \
      "sentry-sdk>=2.17,<3" \
      "pydantic>=2.9,<3" \
      "pydantic-settings>=2.5,<3" \
      "sqlalchemy>=2.0.35,<3" \
      "psycopg[binary,pool]>=3.2,<4" \
      "boto3>=1.35,<2" \
      "pillow>=11.0,<12" \
      "pdf2image>=1.17,<2" \
      "pypdf>=5.1,<6"

COPY apps/worker /app

CMD ["python", "-m", "worker.main"]
