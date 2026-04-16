"""Unit tests for PDF validation + metadata extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from worker.pipeline import pdf
from worker.pipeline.errors import (
    CorruptedPdfError,
    EncryptedPdfError,
    InvalidPdfError,
)


def _write_blank_pdf(
    path: Path, *, pages: int = 1, width: float = 612, height: float = 792
) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=height)
    with path.open("wb") as fh:
        writer.write(fh)


class TestValidate:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(InvalidPdfError):
            pdf.validate_and_extract_metadata(tmp_path / "nope.pdf")

    def test_empty_file_raises(self, tmp_path):
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        with pytest.raises(InvalidPdfError):
            pdf.validate_and_extract_metadata(empty)

    def test_non_pdf_magic_rejected(self, tmp_path):
        bogus = tmp_path / "fake.pdf"
        bogus.write_bytes(b"not a pdf at all, just text")
        with pytest.raises(InvalidPdfError) as ei:
            pdf.validate_and_extract_metadata(bogus)
        assert "magic" in str(ei.value).lower()

    def test_pdf_header_but_corrupt_body(self, tmp_path):
        # Has the magic but no real PDF structure.
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"%PDF-1.4\nthis is not a valid pdf\n")
        with pytest.raises(CorruptedPdfError):
            pdf.validate_and_extract_metadata(broken)


class TestSuccessPath:
    def test_single_blank_page(self, tmp_path):
        path = tmp_path / "one.pdf"
        _write_blank_pdf(path, pages=1)
        meta = pdf.validate_and_extract_metadata(path)
        assert meta.page_count == 1
        assert len(meta.page_sizes) == 1
        size = meta.page_sizes[0]
        assert size.width_pts == pytest.approx(612.0)
        assert size.height_pts == pytest.approx(792.0)

    def test_multi_page_dimensions(self, tmp_path):
        path = tmp_path / "many.pdf"
        _write_blank_pdf(path, pages=3, width=842, height=595)  # A4 landscape
        meta = pdf.validate_and_extract_metadata(path)
        assert meta.page_count == 3
        for size in meta.page_sizes:
            assert size.width_pts == pytest.approx(842.0)
            assert size.height_pts == pytest.approx(595.0)


class TestEncryption:
    def test_encrypted_pdf_rejected(self, tmp_path):
        path = tmp_path / "enc.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.encrypt(user_password="secret", owner_password="secret")
        with path.open("wb") as fh:
            writer.write(fh)
        with pytest.raises(EncryptedPdfError):
            pdf.validate_and_extract_metadata(path)
