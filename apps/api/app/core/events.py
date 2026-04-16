"""Drawing-progress event bus backed by Redis pub/sub.

Two directions:

- ``publish`` is called from the worker (and occasionally the API) when
  a drawing transitions state. It fan-outs to any connected WebSocket
  subscriber.
- ``subscribe`` is an async generator used by the WebSocket route. It
  yields incoming messages and returns cleanly when the caller stops
  iterating (or the redis connection drops).

Channel naming: ``atlas:drawing:{id}:events``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

import redis as redis_sync
import redis.asyncio as aioredis
import structlog

from app.core.config import get_settings

log = structlog.get_logger("atlas.events")


def _channel(drawing_id: UUID | str) -> str:
    return f"atlas:drawing:{drawing_id}:events"


def publish(drawing_id: UUID | str, payload: dict) -> int:
    """Publish a JSON payload on the drawing's channel.

    Returns the number of subscribers that received the message. Never
    raises — publish failures are logged and swallowed so they can't
    break a worker job.
    """
    channel = _channel(drawing_id)
    body = json.dumps(payload, default=str)
    try:
        client = redis_sync.Redis.from_url(get_settings().redis_url, decode_responses=True)
        return client.publish(channel, body)
    except Exception:
        log.exception("events.publish_failed", channel=channel)
        return 0


async def subscribe(drawing_id: UUID | str) -> AsyncIterator[dict]:
    """Async iterator over events on the drawing's channel.

    The subscriber exits cleanly on redis disconnect or on
    ``asyncio.CancelledError`` — callers should rely on cancellation to
    stop consuming when a WebSocket client disconnects.
    """
    channel = _channel(drawing_id)
    client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                await asyncio.sleep(0)  # give control back for heartbeats
                continue
            try:
                yield json.loads(msg["data"])
            except json.JSONDecodeError:
                log.warning("events.bad_json", channel=channel, raw=msg["data"])
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await client.aclose()
        except Exception:
            log.exception("events.cleanup_failed", channel=channel)
