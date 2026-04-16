"""Health endpoints.

- `/health` — liveness. Cheap; does NOT touch dependencies. Kubernetes /
  load balancers use this to decide whether the process is alive.
- `/health/ready` — readiness. Pings Postgres and Redis. Returns 503 if
  either dependency is unreachable, with per-dependency detail.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import db, redis
from app.core.config import get_settings

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    environment: str
    version: str = "0.1.0"


class DependencyStatus(BaseModel):
    ok: bool
    error: str | None = None


class Readiness(BaseModel):
    status: str
    checks: dict[str, DependencyStatus]


@router.get("/health", response_model=Health)
def liveness() -> Health:
    return Health(status="ok", environment=get_settings().environment)


@router.get(
    "/health/ready",
    response_model=Readiness,
    responses={503: {"model": Readiness}},
)
def readiness() -> JSONResponse:
    checks: dict[str, DependencyStatus] = {}

    try:
        db.ping()
        checks["postgres"] = DependencyStatus(ok=True)
    except Exception as exc:
        checks["postgres"] = DependencyStatus(ok=False, error=str(exc)[:200])

    try:
        redis.ping()
        checks["redis"] = DependencyStatus(ok=True)
    except Exception as exc:
        checks["redis"] = DependencyStatus(ok=False, error=str(exc)[:200])

    all_ok = all(c.ok for c in checks.values())
    payload = Readiness(
        status="ready" if all_ok else "unready",
        checks=checks,
    )
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content=payload.model_dump(),
    )
