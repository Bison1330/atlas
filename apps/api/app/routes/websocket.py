"""WebSocket endpoint for live ingest progress.

Connection lifecycle:

1. Client opens ``/ws/drawings/{id}``.
2. Server accepts, looks up the drawing. If not found, closes with
   code 4004 (application-specific "not found") and a reason.
3. Server sends an initial snapshot (current status + progress).
4. Server subscribes to Redis pub/sub on ``atlas:drawing:{id}:events``
   and forwards every message to the client as JSON.
5. A heartbeat task pings every ``_HEARTBEAT_INTERVAL`` seconds so
   stalled intermediaries don't silently drop the connection; if a
   ping fails the connection is closed.
6. If the client disconnects (clean close, network error, heartbeat
   failure), the subscriber task is cancelled and Redis cleanup runs.

Close codes used:
- 1000  normal
- 1011  internal server error
- 4004  drawing not found
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import UUID

import structlog
from atlas_core import IngestStatus, IngestStatusEvent
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core import events
from app.core.db import get_session_factory
from app.schemas.errors import NotFoundError
from app.services.drawings import get_drawing

router = APIRouter(prefix="/ws", tags=["websocket"])
log = structlog.get_logger("atlas.ws")

_HEARTBEAT_INTERVAL = 20.0  # seconds
_CLOSE_NOT_FOUND = 4004
_CLOSE_INTERNAL = 1011


@router.websocket("/drawings/{drawing_id}")
async def drawing_progress(websocket: WebSocket, drawing_id: UUID) -> None:
    await websocket.accept()

    # Initial snapshot — uses its own short-lived session and closes it.
    SessionLocal = get_session_factory()
    session: Session = SessionLocal()
    try:
        try:
            drawing = get_drawing(session, drawing_id)
        except NotFoundError:
            await websocket.close(code=_CLOSE_NOT_FOUND, reason="drawing not found")
            return

        snapshot = IngestStatusEvent(
            drawing_id=drawing.id,
            status=IngestStatus(drawing.status),
            progress_percent=drawing.progress_percent,
            message=drawing.progress_message,
            error_code=drawing.error_code,
            at=drawing.updated_at if drawing.updated_at else datetime.now(UTC),
        )
    finally:
        session.close()

    await websocket.send_json({"type": "snapshot", "event": snapshot.model_dump(mode="json")})

    forward_task = asyncio.create_task(_forward_events(websocket, drawing_id))
    heartbeat_task = asyncio.create_task(_heartbeat(websocket))

    try:
        # Wait on whichever task finishes first (client disconnect,
        # heartbeat failure, or subscriber exit).
        done, pending = await asyncio.wait(
            {forward_task, heartbeat_task, asyncio.create_task(_reader(websocket))},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
    except Exception:
        log.exception("ws.dispatch_failed", drawing_id=str(drawing_id))
        with contextlib.suppress(Exception):
            await websocket.close(code=_CLOSE_INTERNAL)
    finally:
        for t in (forward_task, heartbeat_task):
            if not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t


async def _forward_events(websocket: WebSocket, drawing_id: UUID) -> None:
    try:
        async for event in events.subscribe(drawing_id):
            await websocket.send_json({"type": "event", "event": event})
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("ws.forward_failed", drawing_id=str(drawing_id))


async def _heartbeat(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            await websocket.send_json({"type": "ping", "at": datetime.now(UTC).isoformat()})
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception:
        # Any other error on the socket — treat as disconnect.
        pass


async def _reader(websocket: WebSocket) -> None:
    """Drain incoming client messages so a clean-close is detected promptly.

    We don't expect clients to send anything (except pong-style acks),
    but calling receive() is the only way to notice a disconnect from
    the server side.
    """
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
