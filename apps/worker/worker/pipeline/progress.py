"""Progress + event-publishing helper for the ingest pipeline.

Every meaningful state transition funnels through ``ProgressReporter``:

1. The drawing (and optionally a sheet) row is updated in Postgres.
2. An ``IngestStatusEvent`` is published on the drawing's pub/sub
   channel so the WebSocket endpoint can forward it to the frontend.

Both steps run inside the caller's session but ``commit`` is up to
them — the reporter doesn't commit, letting the orchestrator batch
updates together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from atlas_core import IngestStatus, IngestStatusEvent
from atlas_db import Drawing, Sheet
from sqlalchemy.orm import Session

from worker import events

log = structlog.get_logger("atlas.worker.progress")


class ProgressReporter:
    """Emit progress updates and events for a single ingest run."""

    def __init__(self, session: Session, drawing: Drawing) -> None:
        self._session = session
        self._drawing = drawing

    @property
    def drawing_id(self) -> UUID:
        return self._drawing.id

    def drawing(
        self,
        *,
        status: IngestStatus,
        percent: int,
        message: str,
    ) -> None:
        """Update the drawing row + publish an event."""
        self._drawing.status = status.value
        self._drawing.progress_percent = max(0, min(100, percent))
        self._drawing.progress_message = message
        if status is IngestStatus.COMPLETED:
            self._drawing.completed_at = datetime.now(UTC)
        elif status is IngestStatus.FAILED:
            self._drawing.failed_at = datetime.now(UTC)

        self._session.add(self._drawing)
        self._session.flush()

        events.publish(
            self._drawing.id,
            IngestStatusEvent(
                drawing_id=self._drawing.id,
                status=status,
                progress_percent=self._drawing.progress_percent,
                message=message,
                at=datetime.now(UTC),
            ).model_dump(mode="json"),
        )

        log.info(
            "progress.drawing",
            drawing_id=str(self._drawing.id),
            status=status.value,
            percent=self._drawing.progress_percent,
            message=message,
        )

    def sheet(
        self,
        sheet: Sheet,
        *,
        status: IngestStatus,
        percent: int,
        overall_percent: int,
        overall_message: str,
    ) -> None:
        """Update a sheet row + bump the drawing's overall progress."""
        sheet.status = status.value
        sheet.progress_percent = max(0, min(100, percent))
        if status is IngestStatus.COMPLETED:
            sheet.completed_at = datetime.now(UTC)
        self._session.add(sheet)

        if status is IngestStatus.RASTERIZING:
            self._drawing.status = IngestStatus.RASTERIZING.value
        elif status is IngestStatus.TILING:
            self._drawing.status = IngestStatus.TILING.value
        self._drawing.progress_percent = max(0, min(100, overall_percent))
        self._drawing.progress_message = overall_message
        self._session.add(self._drawing)
        self._session.flush()

        events.publish(
            self._drawing.id,
            IngestStatusEvent(
                drawing_id=self._drawing.id,
                sheet_id=sheet.id,
                status=status,
                progress_percent=self._drawing.progress_percent,
                message=overall_message,
                at=datetime.now(UTC),
            ).model_dump(mode="json"),
        )

    def fail(self, *, code: str, message: str) -> None:
        """Mark the drawing as failed with a typed error code + message."""
        self._drawing.status = IngestStatus.FAILED.value
        self._drawing.error_code = code
        self._drawing.error_message = message
        self._drawing.failed_at = datetime.now(UTC)
        self._session.add(self._drawing)
        self._session.flush()

        events.publish(
            self._drawing.id,
            IngestStatusEvent(
                drawing_id=self._drawing.id,
                status=IngestStatus.FAILED,
                progress_percent=self._drawing.progress_percent,
                message=message,
                error_code=code,
                at=datetime.now(UTC),
            ).model_dump(mode="json"),
        )

        log.error(
            "progress.fail",
            drawing_id=str(self._drawing.id),
            error_code=code,
            error_message=message,
        )
