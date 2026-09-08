"""Repository 測試：防重複與領取待處理記錄。"""

import threading
from datetime import datetime, timezone

import pytest
from django.db import connection, transaction

from backup import repository
from backup.models import BackupRecord, BackupStatus, RawEvent
from backup.tests.conftest import make_record

pytestmark = pytest.mark.django_db

FIELDS = {
    "webhook_event_id": "evt-1",
    "line_message_id": "msg-1",
    "source_type": "user",
    "source_id": "U-user-1",
    "sender_id": "U-user-1",
    "message_type": "text",
    "line_timestamp": datetime(2026, 5, 7, tzinfo=timezone.utc),
}


def test_create_pending_record(raw_event):
    record = repository.create_pending_backup_record(raw_event=raw_event, **FIELDS)

    assert record is not None
    assert record.status == BackupStatus.PENDING


def test_duplicate_returns_none_instead_of_raising(raw_event):
    """重複事件是正常情況，不該讓 Webhook 回 500（UC-3）。"""
    repository.create_pending_backup_record(raw_event=raw_event, **FIELDS)

    duplicate = repository.create_pending_backup_record(raw_event=raw_event, **FIELDS)

    assert duplicate is None
    assert BackupRecord.objects.count() == 1


def test_duplicate_does_not_break_later_inserts(raw_event):
    """一筆重複被擋下之後，同一批的其他事件仍要能存進去。"""
    repository.create_pending_backup_record(raw_event=raw_event, **FIELDS)
    repository.create_pending_backup_record(raw_event=raw_event, **FIELDS)

    other = repository.create_pending_backup_record(
        raw_event=raw_event, **{**FIELDS, "webhook_event_id": "evt-2", "line_message_id": "msg-2"}
    )

    assert other is not None
    assert BackupRecord.objects.count() == 2


def test_claim_returns_none_when_nothing_pending(db):
    assert repository.claim_next_pending() is None


def test_claim_increments_attempts(raw_event):
    make_record(raw_event)

    claimed = repository.claim_next_pending()

    assert claimed is not None
    assert claimed.attempts == 1


def test_claim_skips_non_pending_records(raw_event):
    make_record(raw_event, status=BackupStatus.SUCCESS)

    assert repository.claim_next_pending() is None


def test_excluded_records_are_not_claimed_again(raw_event):
    """同一輪 worker 不會重複領到剛處理過、又被放回 PENDING 的記錄。"""
    record = make_record(raw_event, webhook_event_id="evt-1", line_message_id="msg-1")

    assert repository.claim_next_pending(exclude_ids=[record.pk]) is None


def test_second_worker_gets_the_next_record(raw_event):
    first_record = make_record(raw_event, webhook_event_id="evt-1", line_message_id="msg-1")
    make_record(raw_event, webhook_event_id="evt-2", line_message_id="msg-2")

    first = repository.claim_next_pending()
    second = repository.claim_next_pending(exclude_ids=[first.pk])

    assert first.pk == first_record.pk
    assert {first.pk, second.pk} == set(BackupRecord.objects.values_list("pk", flat=True))


@pytest.mark.django_db(transaction=True)
def test_claim_skips_locked_record_held_by_another_connection():
    """驗證 `SELECT ... FOR UPDATE SKIP LOCKED` 真的有效。

    用 `transaction=True` 讓資料真的 commit 到資料庫，再開一條獨立的資料庫連線，
    在它自己的交易裡鎖住一筆記錄（模擬另一個 worker 正在處理它、還沒提交）。
    驗證 `claim_next_pending()` 會跳過被鎖住的那筆、改領到另一筆，而不是卡住
    等待鎖釋放——這裡不能用 `raw_event`／`make_record` 依賴的 `db` fixture，
    因為它跟 `transaction=True` 互斥（pytest-django 的限制），所以資料在測試裡自己建。
    """
    raw = RawEvent.objects.create(payload={"events": []})
    locked_record = make_record(raw, webhook_event_id="evt-1", line_message_id="msg-1")
    other_record = make_record(raw, webhook_event_id="evt-2", line_message_id="msg-2")

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_lock_in_another_connection() -> None:
        with transaction.atomic():
            BackupRecord.objects.select_for_update().filter(pk=locked_record.pk).first()
            lock_acquired.set()
            release_lock.wait(timeout=5)
        connection.close()

    holder = threading.Thread(target=hold_lock_in_another_connection)
    holder.start()
    assert lock_acquired.wait(timeout=5), "另一條連線沒有成功拿到鎖"

    try:
        claimed = repository.claim_next_pending()
    finally:
        release_lock.set()
        holder.join(timeout=5)

    assert claimed is not None
    assert claimed.pk == other_record.pk


def test_status_transitions(raw_event):
    record = make_record(raw_event)

    repository.mark_success(record, "notion-page-id")
    assert record.status == BackupStatus.SUCCESS
    assert record.target_ref == "notion-page-id"

    repository.mark_failed(record, "boom")
    assert record.status == BackupStatus.FAILED
    assert record.note == "boom"

    repository.mark_skipped(record, "too big")
    assert record.status == BackupStatus.SKIPPED

    repository.mark_for_retry(record, "timeout")
    record.refresh_from_db()
    assert record.status == BackupStatus.PENDING
