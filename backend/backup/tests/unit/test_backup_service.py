"""備份 Service 與路由表測試（FR-5、FR-6、Edge case 3、5、9）。"""

from datetime import datetime, timezone

import pytest

from backup import repository
from backup.clients.line_client import DownloadedContent
from backup.errors import PermanentError, SkipError, TransientError
from backup.models import BackupStatus, RawEvent
from backup.services.backup_service import (
    BackupRouter,
    MediaBackupService,
    TextBackupService,
    find_event_payload,
)
from backup.tests.conftest import make_message_event, make_payload, make_record
from backup.tests.unit.test_mime import PNG

pytestmark = pytest.mark.django_db


class FakeNotion:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple] = []

    def append_text(self, database_id, text, meta):
        if self.error:
            raise self.error
        self.calls.append((database_id, text, meta))
        return "page-123"


class FakeLine:
    def __init__(self, data: bytes = PNG, error: Exception | None = None):
        self.data = data
        self.error = error

    def download_content(self, message_id):
        if self.error:
            raise self.error
        return DownloadedContent(data=self.data, content_type="image/png")


class FakeDrive:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.uploads: list[tuple] = []
        self.paths: list[list[str]] = []

    def ensure_folder_path(self, root_folder_id, names):
        self.paths.append(names)
        return "folder-1"

    def upload(self, folder_id, filename, data, mime_type):
        if self.error:
            raise self.error
        self.uploads.append((folder_id, filename, data, mime_type))
        return "file-123"


def make_text_record(text: str = "hello"):
    raw_event = RawEvent.objects.create(payload=make_payload(make_message_event(text=text)))
    return make_record(raw_event)


def make_media_record(message_type: str = "image", **message_fields):
    event = make_message_event(message_type=message_type, extra_message_fields=message_fields)
    raw_event = RawEvent.objects.create(payload=make_payload(event))
    return make_record(raw_event, message_type=message_type)


# --- TextBackupService ---


def test_text_backup_writes_to_notion_and_marks_success():
    record = make_text_record("hello world")
    notion = FakeNotion()

    TextBackupService(notion=notion, repo=repository).backup(record)

    record.refresh_from_db()
    assert record.status == BackupStatus.SUCCESS
    assert record.target_ref == "page-123"
    assert notion.calls[0][1] == "hello world"


def test_text_backup_passes_metadata():
    record = make_text_record()
    notion = FakeNotion()

    TextBackupService(notion=notion, repo=repository).backup(record)

    meta = notion.calls[0][2]
    assert meta.line_message_id == "msg-1"
    assert meta.source_id == "U-user-1"


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_text_is_skipped_without_calling_notion(text):
    """不建立空的 Notion 資料列（Edge case 3）。"""
    record = make_text_record(text)
    notion = FakeNotion()

    TextBackupService(notion=notion, repo=repository).backup(record)

    record.refresh_from_db()
    assert record.status == BackupStatus.SKIPPED
    assert notion.calls == []


def test_notion_error_propagates_for_retry_service():
    record = make_text_record()
    notion = FakeNotion(error=TransientError("timeout"))

    with pytest.raises(TransientError):
        TextBackupService(notion=notion, repo=repository).backup(record)

    record.refresh_from_db()
    assert record.status == BackupStatus.PENDING


# --- MediaBackupService ---


def test_media_backup_uploads_and_marks_success():
    record = make_media_record()
    drive = FakeDrive()

    MediaBackupService(line=FakeLine(), drive=drive, repo=repository).backup(record)

    record.refresh_from_db()
    assert record.status == BackupStatus.SUCCESS
    assert record.target_ref == "file-123"
    assert drive.uploads[0][3] == "image/png"


def test_media_backup_uses_conversation_year_month_folders():
    record = make_media_record()
    record.line_timestamp = datetime(2026, 5, 7, tzinfo=timezone.utc)
    record.save(update_fields=["line_timestamp"])
    drive = FakeDrive()

    MediaBackupService(line=FakeLine(), drive=drive, repo=repository).backup(record)

    assert drive.paths[0] == ["U-user-1", "2026", "05"]


def test_media_filename_uses_original_name_for_file_messages():
    record = make_media_record(message_type="file", fileName="報告.pdf")
    drive = FakeDrive()

    MediaBackupService(line=FakeLine(), drive=drive, repo=repository).backup(record)

    filename = drive.uploads[0][1]
    assert filename.endswith(".png")  # 副檔名以內容為準，不信任原始檔名
    assert "msg-1" in filename


def test_oversized_media_is_skipped(settings):
    """檔案太大不算失敗（Edge case 5）。"""
    settings.MAX_MEDIA_FILE_SIZE_MB = 0
    record = make_media_record()
    drive = FakeDrive()

    MediaBackupService(line=FakeLine(), drive=drive, repo=repository).backup(record)

    record.refresh_from_db()
    assert record.status == BackupStatus.SKIPPED
    assert drive.uploads == []


def test_disallowed_format_is_skipped():
    record = make_media_record()
    drive = FakeDrive()

    MediaBackupService(line=FakeLine(data=b"not a real file"), drive=drive, repo=repository).backup(
        record
    )

    record.refresh_from_db()
    assert record.status == BackupStatus.SKIPPED


def test_expired_line_content_propagates_as_permanent():
    record = make_media_record()
    line = FakeLine(error=PermanentError("gone"))

    with pytest.raises(PermanentError):
        MediaBackupService(line=line, drive=FakeDrive(), repo=repository).backup(record)


def test_drive_failure_propagates_for_retry_service():
    record = make_media_record()

    with pytest.raises(TransientError):
        MediaBackupService(
            line=FakeLine(), drive=FakeDrive(error=TransientError("503")), repo=repository
        ).backup(record)


def test_media_without_message_id_is_permanent_error():
    record = make_media_record()
    record.line_message_id = None
    record.save(update_fields=["line_message_id"])

    with pytest.raises(PermanentError):
        MediaBackupService(line=FakeLine(), drive=FakeDrive(), repo=repository).backup(record)


# --- find_event_payload / BackupRouter ---


def test_find_event_payload_raises_when_event_is_missing():
    record = make_text_record()
    record.webhook_event_id = "evt-does-not-exist"

    with pytest.raises(PermanentError):
        find_event_payload(record)


@pytest.mark.parametrize("message_type", ["image", "video", "file", "audio"])
def test_router_sends_media_types_to_media_service(message_type):
    text_service, media_service = object(), object()
    routes = {"text": text_service}
    routes.update({name: media_service for name in ("image", "video", "file", "audio")})

    assert BackupRouter(routes=routes).route(message_type) is media_service


def test_router_sends_text_to_text_service():
    text_service = object()

    assert BackupRouter(routes={"text": text_service}).route("text") is text_service


@pytest.mark.parametrize("message_type", ["sticker", "location", "follow", ""])
def test_router_skips_unsupported_types(message_type):
    """貼圖、位置、加入好友等不備份，但也不能讓程式壞掉（Edge case 9、10）。"""
    with pytest.raises(SkipError, match="unsupported"):
        BackupRouter(routes={"text": object()}).route(message_type)
