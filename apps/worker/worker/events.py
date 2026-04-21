"""Drawing-progress publisher.

Fires ``IngestStatusEvent`` payloads onto the same Redis pub/sub channel
the API's WebSocket endpoint subscribes to. Publish failures are logged
but never raise — a transient Redis blip must not kill an ingest job.

**Log-level policy for connection errors.** Redis being unreachable
inside a worker container is a real production incident (pings from
the queue itself would already be failing). In that context we want
the full traceback at ERROR so the oncall page fires. *Outside* a
worker — e.g. ``scripts/seed_demo_account.py`` invoking
:func:`worker.jobs.extract.extract_from_dxf` from the host venv where
``redis:6379`` doesn't resolve — the failure is benign and expected,
and spamming a 40-line traceback per event is pure noise. The worker
entrypoint (:func:`worker.main.run`) sets ``ATLAS_WORKER_PROCESS=1``
to opt into ERROR-level logging; everything else demotes the
connection-error branch to DEBUG. Non-connection exceptions (JSON
encode failure, etc.) stay at ERROR unconditionally — those would be
genuinely surprising in any context.
"""

from __future__ import annotations

import json
import os
from uuid import UUID

import redis as redis_sync
import redis.exceptions
import structlog

from worker.config import get_settings

log = structlog.get_logger("atlas.worker.events")


def _channel(drawing_id: UUID | str) -> str:
    return f"atlas:drawing:{drawing_id}:events"


def _is_worker_process() -> bool:
    return os.environ.get("ATLAS_WORKER_PROCESS") == "1"


def publish(drawing_id: UUID | str, payload: dict) -> int:
    channel = _channel(drawing_id)
    body = json.dumps(payload, default=str)
    try:
        client = redis_sync.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
        return client.publish(channel, body)
    except redis.exceptions.ConnectionError as exc:
        if _is_worker_process():
            log.exception(
                "events.publish_connection_failed", channel=channel,
            )
        else:
            # Outside a worker (seed script, CLI, one-shot tool). The
            # caller can't do anything about it; don't pollute stderr.
            log.debug(
                "events.publish_connection_failed",
                channel=channel,
                error=str(exc),
            )
        return 0
    except Exception:
        log.exception("events.publish_failed", channel=channel)
        return 0
