"""PDF page rasterization.

Renders PDF pages one at a time at a configurable DPI, yielding PIL
images. Using ``convert_from_path`` with ``first_page == last_page``
avoids holding the full document in memory — important for 30+ sheet
construction drawings.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import structlog
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError
from PIL import Image

from worker.pipeline.errors import RasterizationError

log = structlog.get_logger("atlas.worker.pipeline.raster")


def rasterize_pages(path: Path, *, dpi: int) -> Iterator[tuple[int, Image.Image]]:
    """Yield ``(page_number, image)`` for each page in the PDF.

    Page numbers are 1-indexed. The caller is responsible for closing
    each ``PIL.Image`` when done. If any page fails to render, a
    ``RasterizationError`` is raised with the failing page number.
    """
    try:
        from pdf2image import pdfinfo_from_path

        info = pdfinfo_from_path(str(path))
    except PDFInfoNotInstalledError as exc:
        raise RasterizationError(
            "poppler is not installed in this environment — rasterization is unavailable."
        ) from exc
    except PDFPageCountError as exc:
        raise RasterizationError(f"Could not determine PDF page count: {exc}") from exc

    page_count = int(info.get("Pages", 0))
    if page_count == 0:
        raise RasterizationError("PDF reported 0 pages at render time.")

    for page_num in range(1, page_count + 1):
        try:
            images = convert_from_path(
                str(path),
                dpi=dpi,
                first_page=page_num,
                last_page=page_num,
                fmt="png",
                thread_count=1,
                use_pdftocairo=True,
            )
        except PDFSyntaxError as exc:
            raise RasterizationError(
                f"Syntax error rendering page {page_num}: {exc}"
            ) from exc
        except Exception as exc:
            log.exception("raster.render_failed", page=page_num)
            raise RasterizationError(
                f"Failed to render page {page_num}: {exc}"
            ) from exc

        if not images:
            raise RasterizationError(f"No image produced for page {page_num}.")

        yield page_num, images[0]
