"""PDF validation + metadata extraction.

Validates that the uploaded file:
- parses as a PDF (pypdf structural check),
- isn't password-protected,
- contains at least one page.

Returns a ``PdfMetadata`` with per-page point sizes, which the
rasterizer uses to compute rendered pixel dimensions at 300 DPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from worker.pipeline.errors import (
    CorruptedPdfError,
    EmptyPdfError,
    EncryptedPdfError,
    InvalidPdfError,
)

log = structlog.get_logger("atlas.worker.pipeline.pdf")


@dataclass(slots=True)
class PageSize:
    width_pts: float
    height_pts: float


@dataclass(slots=True)
class PdfMetadata:
    page_count: int
    page_sizes: list[PageSize]
    title: str | None = None
    author: str | None = None
    producer: str | None = None
    creation_date: str | None = None


def validate_and_extract_metadata(path: Path) -> PdfMetadata:
    if not path.exists() or path.stat().st_size == 0:
        raise InvalidPdfError("File is missing or empty.")

    # Magic-number sniff. pypdf already does this but the error shape is
    # noisier — check up front for a cleaner message.
    with path.open("rb") as fh:
        head = fh.read(5)
    if not head.startswith(b"%PDF-"):
        raise InvalidPdfError(
            "File does not begin with the PDF magic number (%PDF-)."
        )

    try:
        reader = PdfReader(str(path), strict=False)
    except PdfReadError as exc:
        raise CorruptedPdfError(f"PDF could not be parsed: {exc}") from exc
    except PdfStreamError as exc:
        raise CorruptedPdfError(f"PDF stream error: {exc}") from exc
    except Exception as exc:
        log.exception("pdf.reader_unexpected", path=str(path))
        raise CorruptedPdfError(f"PDF could not be parsed: {exc}") from exc

    if reader.is_encrypted:
        # pypdf lets us try to decrypt with an empty password — only if
        # that works is the PDF effectively open. Anything else → fail.
        try:
            ok = reader.decrypt("") != 0
        except Exception:
            ok = False
        if not ok:
            raise EncryptedPdfError()

    page_count = len(reader.pages)
    if page_count == 0:
        raise EmptyPdfError()

    page_sizes: list[PageSize] = []
    for idx, page in enumerate(reader.pages):
        try:
            media_box = page.mediabox
            width = float(media_box.width)
            height = float(media_box.height)
        except Exception as exc:
            raise CorruptedPdfError(
                f"Could not read dimensions of page {idx + 1}: {exc}"
            ) from exc
        page_sizes.append(PageSize(width_pts=width, height_pts=height))

    meta = reader.metadata or {}
    return PdfMetadata(
        page_count=page_count,
        page_sizes=page_sizes,
        title=_str_or_none(meta.get("/Title")),
        author=_str_or_none(meta.get("/Author")),
        producer=_str_or_none(meta.get("/Producer")),
        creation_date=_str_or_none(meta.get("/CreationDate")),
    )


def _str_or_none(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
