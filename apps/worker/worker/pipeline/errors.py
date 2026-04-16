"""Typed failures raised by the ingest pipeline.

Every ``IngestError`` carries a machine-readable ``code`` and a
user-facing ``message`` — they're persisted verbatim onto the
``drawings`` row so the frontend can display a clear next-action.
"""

from __future__ import annotations


class IngestError(Exception):
    """Base class for every expected pipeline failure."""

    code: str = "ingest_failed"
    message: str = "Ingest failed."

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.message = message
        super().__init__(self.message)


class EncryptedPdfError(IngestError):
    code = "pdf_encrypted"
    message = (
        "The PDF is password-protected. Remove the password in your PDF "
        "editor and upload again."
    )


class CorruptedPdfError(IngestError):
    code = "pdf_corrupted"
    message = "The PDF structure is corrupted and cannot be read."


class InvalidPdfError(IngestError):
    code = "pdf_invalid"
    message = "The uploaded file is not a valid PDF."


class EmptyPdfError(IngestError):
    code = "pdf_empty"
    message = "The PDF contains no pages."


class RasterizationError(IngestError):
    code = "rasterization_failed"
    message = "Failed to render one or more PDF pages."


class TilingError(IngestError):
    code = "tiling_failed"
    message = "Failed to generate tiles for one or more pages."


class StorageError(IngestError):
    code = "storage_error"
    message = "Failed to read from or write to object storage."
