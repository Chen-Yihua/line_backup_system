"""檔案格式與大小檢查測試（Edge case 5）。"""

import pytest

from backup.errors import SkipError
from backup.utils.mime import MEGABYTE, detect_file_type, validate_media

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 32
MP4 = b"\x00\x00\x00\x18" + b"ftyp" + b"isom" + b"0" * 32
M4A = b"\x00\x00\x00\x18" + b"ftyp" + b"M4A " + b"0" * 32
PDF = b"%PDF-1.7" + b"0" * 32


@pytest.mark.parametrize(
    ("data", "expected_mime", "expected_ext"),
    [
        (PNG, "image/png", ".png"),
        (JPEG, "image/jpeg", ".jpg"),
        (WEBP, "image/webp", ".webp"),
        (MP4, "video/mp4", ".mp4"),
        (M4A, "audio/mp4", ".m4a"),
        (PDF, "application/pdf", ".pdf"),
    ],
)
def test_detects_type_from_content(data, expected_mime, expected_ext):
    file_type = detect_file_type(data)

    assert file_type is not None
    assert (file_type.mime, file_type.extension) == (expected_mime, expected_ext)


def test_unknown_content_is_not_detected():
    assert detect_file_type(b"this is just some text") is None


def test_extension_is_not_trusted():
    """副檔名說是 .png，但內容是 JPEG——以內容為準。"""
    assert detect_file_type(JPEG).mime == "image/jpeg"


def test_validate_passes_for_allowed_file():
    assert validate_media(PNG, max_size_mb=1).mime == "image/png"


def test_oversized_file_is_skipped():
    oversized = PNG + b"0" * (2 * MEGABYTE)

    with pytest.raises(SkipError, match="過大"):
        validate_media(oversized, max_size_mb=1)


def test_disallowed_format_is_skipped():
    with pytest.raises(SkipError, match="格式"):
        validate_media(b"plain text pretending to be a file", max_size_mb=1)


def test_empty_file_is_skipped():
    with pytest.raises(SkipError):
        validate_media(b"", max_size_mb=1)
