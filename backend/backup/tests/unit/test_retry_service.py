"""RetryService 測試（FR-7、FR-9、docs/workflow.md「Retry」）。"""

import pytest

from backup import repository
from backup.errors import PermanentError, SkipError, TransientError
from backup.models import BackupStatus
from backup.services.backup_service import BackupRouter
from backup.services.retry_service import RetryService, pending_count
from backup.tests.conftest import make_record

pytestmark = pytest.mark.django_db


class FakeService:
    """成功時把記錄標成 SUCCESS，或依設定丟出例外。"""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def backup(self, record):
        self.calls += 1
        if self.error:
            raise self.error
        repository.mark_success(record, "target-1")


def run_with(service, raw_event, max_attempts: int = 3, **record_fields):
    record = make_record(raw_event, **record_fields)
    router = BackupRouter(routes={record.message_type: service})
    RetryService(router=router, repo=repository, max_attempts=max_attempts).run_once()
    record.refresh_from_db()
    return record


def test_no_pending_record_returns_none(db):
    assert RetryService(router=BackupRouter(routes={}), repo=repository).run_once() is None


def test_success_marks_record_success(raw_event):
    record = run_with(FakeService(), raw_event)

    assert record.status == BackupStatus.SUCCESS
    assert record.target_ref == "target-1"
    assert record.attempts == 1


def test_unsupported_type_is_skipped(raw_event):
    """Router 找不到對應 Service 就標記 SKIPPED（Edge case 9）。"""
    record = make_record(raw_event, message_type="sticker")
    RetryService(router=BackupRouter(routes={}), repo=repository).run_once()

    record.refresh_from_db()
    assert record.status == BackupStatus.SKIPPED
    assert "unsupported" in record.note


def test_skip_error_marks_skipped(raw_event):
    record = run_with(FakeService(error=SkipError("檔案過大")), raw_event)

    assert record.status == BackupStatus.SKIPPED
    assert record.note == "檔案過大"


def test_permanent_error_fails_without_retry(raw_event):
    record = run_with(FakeService(error=PermanentError("內容已過期")), raw_event)

    assert record.status == BackupStatus.FAILED
    assert record.attempts == 1


def test_transient_error_goes_back_to_pending(raw_event):
    record = run_with(FakeService(error=TransientError("timeout")), raw_event)

    assert record.status == BackupStatus.PENDING
    assert record.attempts == 1
    assert record.note == "timeout"


def test_transient_error_fails_after_max_attempts(raw_event):
    """重試上限用完就停手，不會無限重試（FR-7）。"""
    record = run_with(FakeService(error=TransientError("timeout")), raw_event, attempts=2)

    assert record.status == BackupStatus.FAILED
    assert record.attempts == 3
    assert "重試 3 次" in record.note


def test_unexpected_error_does_not_crash_the_worker(raw_event):
    record = run_with(FakeService(error=RuntimeError("bug")), raw_event)

    assert record.status == BackupStatus.PENDING
    assert "RuntimeError" in record.note


def test_retry_eventually_succeeds(raw_event):
    """第一次 timeout、第二次成功——記錄要變回 SUCCESS。"""
    service = FakeService(error=TransientError("timeout"))
    record = make_record(raw_event)
    retry_service = RetryService(
        router=BackupRouter(routes={"text": service}), repo=repository, max_attempts=3
    )

    retry_service.run_once()
    service.error = None
    retry_service.run_once()

    record.refresh_from_db()
    assert record.status == BackupStatus.SUCCESS
    assert record.attempts == 2


def test_run_processes_multiple_records(raw_event):
    make_record(raw_event, webhook_event_id="evt-1", line_message_id="msg-1")
    make_record(raw_event, webhook_event_id="evt-2", line_message_id="msg-2")
    router = BackupRouter(routes={"text": FakeService()})

    processed = RetryService(router=router, repo=repository).run(limit=10)

    assert processed == 2
    assert pending_count() == 0


def test_run_respects_limit(raw_event):
    make_record(raw_event, webhook_event_id="evt-1", line_message_id="msg-1")
    make_record(raw_event, webhook_event_id="evt-2", line_message_id="msg-2")
    router = BackupRouter(routes={"text": FakeService()})

    processed = RetryService(router=router, repo=repository).run(limit=1)

    assert processed == 1
    assert pending_count() == 1
