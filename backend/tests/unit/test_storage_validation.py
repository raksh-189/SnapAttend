"""Unit tests for upload validation and local storage."""

import pytest

from app.core.exceptions import ValidationFailedError
from app.services.student_service import validate_image_upload
from app.storage.base import validate_key
from app.storage.local import LocalStorage

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_jpeg_and_png_accepted():
    assert validate_image_upload(JPEG) == "jpg"
    assert validate_image_upload(PNG) == "png"


def test_non_image_rejected():
    with pytest.raises(ValidationFailedError):
        validate_image_upload(b"GIF89a not accepted")
    with pytest.raises(ValidationFailedError):
        validate_image_upload(b"<html>nope</html>")


def test_oversize_rejected(monkeypatch):
    from app.core.config import get_settings

    big = JPEG + b"0" * (get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024)
    with pytest.raises(ValidationFailedError):
        validate_image_upload(big)


def test_storage_key_traversal_rejected():
    for bad in ("../etc/passwd", "/abs/path", "a/../../b"):
        with pytest.raises(ValueError):
            validate_key(bad)
    assert validate_key("enrollment/x/y.jpg") == "enrollment/x/y.jpg"


def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorage(root=str(tmp_path))
    key = storage.save("enrollment/s1/a.jpg", b"bytes")
    assert storage.exists(key)
    assert storage.get(key) == b"bytes"
    storage.delete(key)
    assert not storage.exists(key)
    storage.delete(key)  # idempotent
