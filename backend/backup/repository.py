"""唯一可以直接操作資料庫的地方（見 docs/architecture.md Repository Pattern）。

防重複（FR-8）在這裡把關：靠資料庫的 UNIQUE constraint，
不是先 `exists()` 再 `create()`——後者在兩個重複事件同時到達時會有 race condition。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction

from backup.models import BackupRecord, BackupStatus, RawEvent


def create_raw_event(payload: dict[str, Any]) -> RawEvent:
    """把整包 Webhook 原始內容存起來（稽核用）。"""
    return RawEvent.objects.create(payload=payload)


def create_pending_backup_record(
    *,
    raw_event: RawEvent,
    webhook_event_id: str,
    line_message_id: str | None,
    source_type: str,
    source_id: str,
    sender_id: str | None,
    message_type: str,
    line_timestamp: datetime,
) -> BackupRecord | None:
    """建立一筆 PENDING 記錄；已存在（重複事件）就回傳 None。

    用 `IntegrityError` 接住唯一限制，讓「重複」變成正常結果而不是錯誤，
    呼叫端據此決定要不要略過（見 docs/workflow.md「Duplicate」）。
    """
    try:
        # 巢狀 atomic：讓 IntegrityError 只回捲這一筆，不影響同批其他事件。
        with transaction.atomic():
            return BackupRecord.objects.create(
                raw_event=raw_event,
                webhook_event_id=webhook_event_id,
                line_message_id=line_message_id,
                source_type=source_type,
                source_id=source_id,
                sender_id=sender_id,
                message_type=message_type,
                line_timestamp=line_timestamp,
                status=BackupStatus.PENDING,
            )
    except IntegrityError:
        return None


def claim_next_pending(exclude_ids: Iterable[int] = ()) -> BackupRecord | None:
    """領取一筆待處理記錄，並確保兩個 worker 不會搶到同一筆。

    用 PostgreSQL 標準的 `SELECT ... FOR UPDATE SKIP LOCKED`：在交易內鎖住
    候選記錄，另一個 worker 同時查詢時會直接跳過被鎖住的列去挑下一筆，
    不是卡住等待——這是資料庫層級處理「多個 worker 搶同一份工作佇列」的
    標準做法，不用自己刻重試迴圈（見 docs/architecture.md Flow 2）。

    `exclude_ids` 讓同一輪 worker 不會重複領到剛剛處理過、又被放回 `PENDING`
    等待下次重試的記錄。

    Worker 中途掛掉時記錄會留在 `PENDING`，下次排程自然重跑；
    因為 `attempts` 已經加過了，不會變成無限重試。
    """
    with transaction.atomic():
        record = (
            BackupRecord.objects.select_for_update(skip_locked=True)
            .filter(status=BackupStatus.PENDING)
            .exclude(pk__in=exclude_ids)
            .order_by("id")
            .first()
        )
        if record is None:
            return None

        record.attempts += 1
        record.save(update_fields=["attempts", "updated_at"])

    return record


def mark_success(record: BackupRecord, target_ref: str) -> BackupRecord:
    """備份成功：記下 Notion page id / Drive file id。"""
    return _update(record, status=BackupStatus.SUCCESS, target_ref=target_ref, note=None)


def mark_failed(record: BackupRecord, note: str) -> BackupRecord:
    """重試用完或永久性錯誤：標記失敗並留下原因。"""
    return _update(record, status=BackupStatus.FAILED, note=note)


def mark_skipped(record: BackupRecord, note: str) -> BackupRecord:
    """不符合備份條件：不算失敗，但要留下原因。"""
    return _update(record, status=BackupStatus.SKIPPED, note=note)


def mark_for_retry(record: BackupRecord, note: str) -> BackupRecord:
    """暫時性錯誤且還沒用完次數：放回 PENDING，等下次排程。"""
    return _update(record, status=BackupStatus.PENDING, note=note)


def _update(record: BackupRecord, **fields: Any) -> BackupRecord:
    """統一的欄位更新入口，確保 `updated_at` 一定會被刷新。"""
    for name, value in fields.items():
        setattr(record, name, value)
    record.save(update_fields=[*fields.keys(), "updated_at"])
    return record
