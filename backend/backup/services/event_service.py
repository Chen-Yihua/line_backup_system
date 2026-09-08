"""收下 Webhook 事件、存進資料庫（docs/architecture.md Flow 1）。

這一層不能呼叫 Notion / Drive——LINE 要求 Webhook 快速回應，
所有耗時的工作都留給背景 worker（見 retry_service.py）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backup import repository
from backup.models import RawEvent

logger = logging.getLogger(__name__)

# LINE source.type → payload 裡放 id 的欄位名稱。
_SOURCE_ID_FIELDS = {"user": "userId", "group": "groupId", "room": "roomId"}


@dataclass(frozen=True)
class IngestResult:
    """一次 Webhook 請求的處理結果，給 View 記 log 用（不含訊息內容）。"""

    created: int
    duplicated: int
    invalid: int


class EventService:
    """把一包 Webhook payload 拆成一筆筆 `BackupRecord`。"""

    def __init__(self, repo: Any = repository) -> None:
        """`repo` 可注入，測試時能換成假的 repository。"""
        self._repo = repo

    def ingest(self, payload: dict[str, Any]) -> IngestResult:
        """存原始資料，再逐一建立 PENDING 記錄。

        重複事件不算錯誤——被 UNIQUE constraint 擋下時只是略過，
        呼叫端仍然回 200（UC-3）。
        """
        raw_event = self._repo.create_raw_event(payload)
        events = payload.get("events") or []

        created = duplicated = invalid = 0
        for event in events:
            outcome = self._ingest_one(raw_event, event)
            created += outcome == "created"
            duplicated += outcome == "duplicated"
            invalid += outcome == "invalid"

        logger.info(
            "webhook ingested",
            extra={
                "context": {
                    "raw_event_id": raw_event.pk,
                    "created": created,
                    "duplicated": duplicated,
                    "invalid": invalid,
                }
            },
        )
        return IngestResult(created=created, duplicated=duplicated, invalid=invalid)

    def _ingest_one(self, raw_event: RawEvent, event: dict[str, Any]) -> str:
        """處理單一事件，回傳 created / duplicated / invalid。"""
        fields = parse_event(event)
        if fields is None:
            return "invalid"

        record = self._repo.create_pending_backup_record(raw_event=raw_event, **fields)
        return "created" if record is not None else "duplicated"


def parse_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """把 LINE 事件轉成 `BackupRecord` 需要的欄位；無法解析回傳 None。

    非訊息事件（follow / join / leave 等，Edge case 10）也會被記錄下來，
    `message_type` 存事件類型本身、`line_message_id` 留空，之後由 Router 標成 SKIPPED。
    """
    webhook_event_id = event.get("webhookEventId")
    source = event.get("source") or {}
    source_type = source.get("type")
    if not webhook_event_id or source_type not in _SOURCE_ID_FIELDS:
        return None

    source_id = source.get(_SOURCE_ID_FIELDS[source_type])
    if not source_id:
        return None

    message = event.get("message") or {}
    is_message = event.get("type") == "message"

    return {
        "webhook_event_id": webhook_event_id,
        "line_message_id": message.get("id") if is_message else None,
        "source_type": source_type,
        "source_id": source_id,
        "sender_id": source.get("userId"),
        "message_type": message.get("type", "unknown") if is_message else event.get("type", ""),
        "line_timestamp": _to_datetime(event.get("timestamp")),
    }


def _to_datetime(line_timestamp: Any) -> datetime:
    """LINE 的毫秒 epoch → timezone-aware datetime；缺值就用現在時間。"""
    if isinstance(line_timestamp, (int, float)):
        return datetime.fromtimestamp(line_timestamp / 1000, tz=timezone.utc)
    return datetime.now(tz=timezone.utc)
