"""RQ worker entrypoint.

Connects to Redis and runs a blocking worker loop over the configured
queues (default: ``default``). Sentry is wired in when ``SENTRY_DSN`` is
set so unhandled job exceptions get reported.
"""

from __future__ import annotations

import sentry_sdk
from redis import Redis
from rq import Queue, Worker
from structlog import get_logger

from worker.config import WorkerSettings, get_settings
from worker.logging import configure_logging


def _init_sentry(settings: WorkerSettings) -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        send_default_pii=False,
        traces_sample_rate=0.1 if settings.is_production else 0.0,
    )


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, production=settings.is_production)
    _init_sentry(settings)

    log = get_logger("atlas.worker")
    conn = Redis.from_url(settings.redis_url)
    conn.ping()

    queues = [Queue(name, connection=conn) for name in settings.queue_list]
    log.info(
        "worker.startup",
        environment=settings.environment,
        queues=settings.queue_list,
        sentry=bool(settings.sentry_dsn),
    )

    Worker(queues, connection=conn).work(with_scheduler=True)


if __name__ == "__main__":
    run()
