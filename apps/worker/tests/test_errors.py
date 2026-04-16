"""Sanity-check the typed pipeline errors carry stable codes + messages."""

from __future__ import annotations

import pytest

from worker.pipeline import errors


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (errors.EncryptedPdfError, "pdf_encrypted"),
        (errors.CorruptedPdfError, "pdf_corrupted"),
        (errors.InvalidPdfError, "pdf_invalid"),
        (errors.EmptyPdfError, "pdf_empty"),
        (errors.RasterizationError, "rasterization_failed"),
        (errors.TilingError, "tiling_failed"),
        (errors.StorageError, "storage_error"),
    ],
)
def test_error_codes_are_stable(cls, code):
    err = cls()
    assert err.code == code
    assert err.message  # never empty
    assert isinstance(err, errors.IngestError)


def test_custom_message_overrides_default():
    err = errors.CorruptedPdfError("totally busted at byte 42")
    assert err.message == "totally busted at byte 42"
    assert err.code == "pdf_corrupted"


def test_codes_are_unique():
    classes = [
        errors.EncryptedPdfError,
        errors.CorruptedPdfError,
        errors.InvalidPdfError,
        errors.EmptyPdfError,
        errors.RasterizationError,
        errors.TilingError,
        errors.StorageError,
    ]
    codes = {c.code for c in classes}
    assert len(codes) == len(classes), "duplicate error codes detected"
