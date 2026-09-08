"""資料模型的唯一限制測試（FR-8、Edge case 2、11）。

重點是確認「擋重複」真的是資料庫在擋，不是程式邏輯。
"""

import pytest
from django.db import IntegrityError

from backup.models import BackupRecord, BackupStatus
from backup.tests.conftest import make_record

pytestmark = pytest.mark.django_db


def test_duplicate_webhook_event_id_is_rejected_by_database(raw_event):
    make_record(raw_event)

    with pytest.raises(IntegrityError):
        make_record(raw_event, line_message_id="msg-2")


def test_duplicate_line_message_id_is_rejected_by_database(raw_event):
    make_record(raw_event)

    with pytest.raises(IntegrityError):
        make_record(raw_event, webhook_event_id="evt-2")


def test_multiple_records_may_have_no_line_message_id(raw_event):
    """非訊息事件（follow / join）沒有 message id，不能因此互相衝突。"""
    make_record(raw_event, webhook_event_id="evt-1", line_message_id=None, message_type="follow")
    make_record(raw_event, webhook_event_id="evt-2", line_message_id=None, message_type="join")

    assert BackupRecord.objects.filter(line_message_id__isnull=True).count() == 2


def test_new_record_defaults_to_pending(raw_event):
    record = make_record(raw_event)

    assert record.status == BackupStatus.PENDING
    assert record.attempts == 0
