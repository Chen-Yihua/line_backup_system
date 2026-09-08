"""檔案格式與大小檢查（docs/security.md、Edge case 5）。

判斷格式時只看內容的 magic bytes，不信任副檔名或 LINE 回傳的 Content-Type
——那兩個都可以被偽造。不認得的格式一律擋下來。
"""

from __future__ import annotations

from dataclasses import dataclass

from backup.errors import SkipError

MEGABYTE = 1024 * 1024


@dataclass(frozen=True)
class FileType:
    """辨識出來的檔案型別。"""

    mime: str
    extension: str


# (offset, magic bytes) → 檔案型別。順序有意義：先比對比較長、比較精確的簽章。
_SIGNATURES: tuple[tuple[int, bytes, FileType], ...] = (
    (0, b"\x89PNG\r\n\x1a\n", FileType("image/png", ".png")),
    (0, b"\xff\xd8\xff", FileType("image/jpeg", ".jpg")),
    (0, b"GIF87a", FileType("image/gif", ".gif")),
    (0, b"GIF89a", FileType("image/gif", ".gif")),
    (0, b"OggS", FileType("audio/ogg", ".ogg")),
    (0, b"ID3", FileType("audio/mpeg", ".mp3")),
    (0, b"%PDF-", FileType("application/pdf", ".pdf")),
    (0, b"PK\x03\x04", FileType("application/zip", ".zip")),
)

# RIFF 容器要再看第 8 個 byte 起的格式名稱才知道是圖片還是聲音。
_RIFF_FORMATS = {
    b"WEBP": FileType("image/webp", ".webp"),
    b"WAVE": FileType("audio/wav", ".wav"),
}

# ISO base media（mp4 家族）看的是 ftyp brand：M4A 開頭是語音，其餘當影片。
_M4A_BRANDS = (b"M4A ", b"M4B ")


def detect_file_type(data: bytes) -> FileType | None:
    """用內容判斷檔案格式；不認得回傳 None。"""
    for offset, magic, file_type in _SIGNATURES:
        if data[offset : offset + len(magic)] == magic:
            return file_type

    if data[:4] == b"RIFF" and data[8:12] in _RIFF_FORMATS:
        return _RIFF_FORMATS[data[8:12]]

    if data[4:8] == b"ftyp":
        is_audio = data[8:12] in _M4A_BRANDS
        return FileType("audio/mp4", ".m4a") if is_audio else FileType("video/mp4", ".mp4")

    return None


def validate_media(data: bytes, max_size_mb: int) -> FileType:
    """檢查大小與格式，通過就回傳辨識結果。

    不符合條件時丟 `SkipError`——這不是失敗，是「不該備份」（狀態記為 SKIPPED）。
    """
    if not data:
        raise SkipError("檔案內容是空的")

    max_bytes = max_size_mb * MEGABYTE
    if len(data) > max_bytes:
        raise SkipError(f"檔案過大：{len(data)} bytes，上限 {max_size_mb} MB")

    file_type = detect_file_type(data)
    if file_type is None:
        raise SkipError("不允許的檔案格式")

    return file_type
