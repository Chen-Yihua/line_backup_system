"""實際做備份的地方：文字 → Notion、媒體 → Google Drive。

分工：
- Service 負責「業務上的結果」——成功寫 `SUCCESS`、不該備份寫 `SKIPPED`。
- 失敗要不要重試由 `retry_service.py` 決定，所以這裡遇到外部錯誤直接往上丟。

訊息內容本身沒有存在 `BackupRecord`（見 docs/database.md），要回 `RawEvent.payload`
裡撈——這也是當初把原始資料另外存一張表的原因。
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from django.conf import settings

from backup import repository
from backup.clients.drive_client import DriveClient
from backup.clients.line_client import LineClient
from backup.clients.notion_client import MessageMeta, NotionClient
from backup.errors import PermanentError, SkipError
from backup.models import BackupRecord
from backup.utils.mime import validate_media

MEDIA_MESSAGE_TYPES = ("image", "video", "file", "audio")
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\-]+")


class BackupService(Protocol):
    """所有備份 Service 的共同介面。"""

    def backup(self, record: BackupRecord) -> None:
        """備份一筆記錄；外部錯誤往上丟給 RetryService 處理。"""


class TextBackupService:
    """文字訊息 → Notion（FR-5）。"""

    def __init__(self, notion: NotionClient | None = None, repo: Any = repository) -> None:
        """Client 與 repository 都可注入，測試時不用真的打 Notion。"""
        self._notion = notion or NotionClient()
        self._repo = repo

    def backup(self, record: BackupRecord) -> None:
        """把訊息文字寫成 Notion 的一頁。"""
        event = find_event_payload(record)
        text = (event.get("message") or {}).get("text") or ""

        # 空白訊息不建立空的 Notion 資料列（Edge case 3）。
        if not text.strip():
            self._repo.mark_skipped(record, "空白文字訊息")
            return

        page_id = self._notion.append_text(settings.NOTION_DATABASE_ID, text, _build_meta(record))
        self._repo.mark_success(record, page_id)


class MediaBackupService:
    """圖片 / 影片 / 檔案 / 語音 → Google Drive（FR-6、docs/workflow.md「Upload」）。"""

    def __init__(
        self,
        line: LineClient | None = None,
        drive: DriveClient | None = None,
        repo: Any = repository,
    ) -> None:
        """兩個 Client 都可注入，測試時不用真的下載或上傳。"""
        self._line = line or LineClient()
        self._drive = drive or DriveClient()
        self._repo = repo

    def backup(self, record: BackupRecord) -> None:
        """下載 → 驗證 → 上傳，三步拆開才知道是哪一步出錯。"""
        if not record.line_message_id:
            raise PermanentError("媒體訊息缺少 line_message_id")

        event = find_event_payload(record)

        try:
            content = self._line.download_content(record.line_message_id)
            file_type = validate_media(content.data, settings.MAX_MEDIA_FILE_SIZE_MB)
        except SkipError as exc:
            # 檔案太大或格式不允許（Edge case 5）——不算失敗。
            self._repo.mark_skipped(record, str(exc))
            return

        folder_id = self._drive.ensure_folder_path(
            settings.GOOGLE_DRIVE_ROOT_FOLDER_ID, _folder_names(record)
        )
        filename = _build_filename(record, event, file_type.extension)
        file_id = self._drive.upload(folder_id, filename, content.data, file_type.mime)

        self._repo.mark_success(record, file_id)


class BackupRouter:
    """依 `message_type` 決定走哪個 Service（Strategy／路由表）。

    用對應表而不是一長串 if/elif：加新的訊息類型只要多一條規則。
    """

    def __init__(self, routes: dict[str, BackupService] | None = None) -> None:
        """`routes` 可注入，測試時能塞假的 Service。"""
        self._routes = routes if routes is not None else _default_routes()

    def route(self, message_type: str) -> BackupService:
        """找不到對應 Service 就丟 `SkipError`（unsupported，Edge case 9、10）。"""
        service = self._routes.get(message_type)
        if service is None:
            raise SkipError(f"unsupported message type: {message_type or 'unknown'}")
        return service


def _default_routes() -> dict[str, BackupService]:
    """正式執行時用的路由表：一個文字 Service、四種媒體共用一個 Service。"""
    text_service = TextBackupService()
    media_service = MediaBackupService()
    routes: dict[str, BackupService] = {"text": text_service}
    routes.update({message_type: media_service for message_type in MEDIA_MESSAGE_TYPES})
    return routes


def find_event_payload(record: BackupRecord) -> dict[str, Any]:
    """從 `RawEvent.payload` 找回這筆記錄對應的原始事件。"""
    events = (record.raw_event.payload or {}).get("events") or []
    for event in events:
        if event.get("webhookEventId") == record.webhook_event_id:
            return event
    raise PermanentError("原始事件不存在，無法備份")


def _build_meta(record: BackupRecord) -> MessageMeta:
    """組出要寫進 Notion 屬性欄位的來源資訊。"""
    return MessageMeta(
        line_message_id=record.line_message_id,
        source_type=record.source_type,
        source_id=record.source_id,
        sender_id=record.sender_id,
        sent_at=record.line_timestamp,
    )


def _folder_names(record: BackupRecord) -> list[str]:
    """Drive 的資料夾階層：對話 / 年 / 月。"""
    return [
        record.source_id,
        f"{record.line_timestamp:%Y}",
        f"{record.line_timestamp:%m}",
    ]


def _build_filename(record: BackupRecord, event: dict[str, Any], extension: str) -> str:
    """檔名帶時間與訊息 id，確保同一個資料夾裡不會互相覆蓋。"""
    original = (event.get("message") or {}).get("fileName")
    stem = _sanitize(original.rsplit(".", 1)[0]) if original else record.message_type
    timestamp = f"{record.line_timestamp:%Y%m%d-%H%M%S}"
    return f"{timestamp}-{record.line_message_id}-{stem}{extension}"


def _sanitize(name: str) -> str:
    """去掉檔名裡可能造成問題的字元。"""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip("_")
    return cleaned[:80] or "file"
