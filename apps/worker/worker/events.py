"""Drawing-progress publisher.

Fires ``IngestStatusEvent`` payloads onto the same Redis pub/sub channel
the API's WebSocket endpoint subscribes to. Publish failures are logged
but never raise — a transient Redis blip must not kill an ingest job.
"""

from __future__ import annotations

import json
from uuid import UUID

import redis as redis_sync
import structlog

from worker.config import get_settings

log = structlog.get_logger("atlas.worker.events")


def _channel(drawing_id: UUID | str) -> str:
    return f"atlas:drawing:{drawing_id}:events"


def publish(drawing_id: UUID | str, payload: dict) -> int:
    channel = _channel(drawing_id)
    body = json.dumps(payload, default=str)
    try:
        client = redis_sync.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
        return client.publish(channel, body)
    except Exception:
        log.exception("events.publish_failed", channel=channel)
        return 0
