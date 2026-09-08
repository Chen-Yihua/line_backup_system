"""整條流程測試：Webhook → 資料庫 → worker → Notion / Drive。

外部 API 全部用假的（NFR：測試不打真的網路）。
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from backup import repository
from backup.models import BackupRecord, BackupStatus
from backup.services.backup_service import BackupRouter, MediaBackupService, TextBackupService
from backup.services.retry_service import RetryService
from backup.tests.conftest import make_message_event, make_payload, sign
from backup.tests.unit.test_backup_service import FakeDrive, FakeLine, FakeNotion

pytestmark = pytest.mark.django_db


def send(client, *events):
    body, signature = sign(make_payload(*events))
    return client.post(
        reverse("line-webhook"),
        data=body,
        content_type="application/json",
        HTTP_X_LINE_SIGNATURE=signature,
    )


def make_router(notion: FakeNotion, line: FakeLine, drive: FakeDrive) -> BackupRouter:
    text_service = TextBackupService(notion=notion, repo=repository)
    media_service = MediaBackupService(line=line, drive=drive, repo=repository)
    routes = {"text": text_service}
    routes.update({name: media_service for name in ("image", "video", "file", "audio")})
    return BackupRouter(routes=routes)


def test_text_message_ends_up_in_notion(client, line_secret):
    send(client, make_message_event(text="重要筆記"))
    notion = FakeNotion()

    RetryService(router=make_router(notion, FakeLine(), FakeDrive()), repo=repository).run()

    record = BackupRecord.objects.get()
    assert record.status == BackupStatus.SUCCESS
    assert record.target_ref == "page-123"
    assert notion.calls[0][1] == "重要筆記"


def test_image_message_ends_up_in_drive(client, line_secret):
    send(client, make_message_event(message_type="image"))
    drive = FakeDrive()

    RetryService(router=make_router(FakeNotion(), FakeLine(), drive), repo=repository).run()

    record = BackupRecord.objects.get()
    assert record.status == BackupStatus.SUCCESS
    assert record.target_ref == "file-123"
    assert drive.uploads[0][3] == "image/png"


def test_mixed_batch_routes_each_message_to_its_target(client, line_secret):
    send(
        client,
        make_message_event(webhook_event_id="evt-1", message_id="msg-1", text="hi"),
        make_message_event(webhook_event_id="evt-2", message_id="msg-2", message_type="image"),
        make_message_event(webhook_event_id="evt-3", message_id="msg-3", message_type="sticker"),
    )

    RetryService(router=make_router(FakeNotion(), FakeLine(), FakeDrive()), repo=repository).run()

    statuses = dict(BackupRecord.objects.values_list("webhook_event_id", "status"))
    assert statuses == {
        "evt-1": BackupStatus.SUCCESS,
        "evt-2": BackupStatus.SUCCESS,
        "evt-3": BackupStatus.SKIPPED,
    }


def test_worker_is_idempotent_for_already_processed_records(client, line_secret):
    """跑第二次不會重複寫入 Notion——記錄已經不是 PENDING 了。"""
    send(client, make_message_event())
    notion = FakeNotion()
    service = RetryService(router=make_router(notion, FakeLine(), FakeDrive()), repo=repository)

    service.run()
    service.run()

    assert len(notion.calls) == 1


def test_management_command_reports_progress(client, line_secret):
    send(client, make_message_event(message_type="sticker"))
    out = StringIO()

    call_command("process_pending_backups", "--limit", "5", stdout=out)

    assert "處理 1 筆" in out.getvalue()
    assert BackupRecord.objects.get().status == BackupStatus.SKIPPED
