"""EventService 與事件解析測試（Flow 1、Edge case 9、10、11）。"""

from datetime import timezone

import pytest

from backup.models import BackupRecord, RawEvent
from backup.services.event_service import EventService, parse_event
from backup.tests.conftest import make_message_event, make_payload

pytestmark = pytest.mark.django_db


def test_ingest_creates_one_record_per_event(db):
    payload = make_payload(
        make_message_event(webhook_event_id="evt-1", message_id="msg-1"),
        make_message_event(webhook_event_id="evt-2", message_id="msg-2", message_type="image"),
    )

    result = EventService().ingest(payload)

    assert result.created == 2
    assert RawEvent.objects.count() == 1
    assert BackupRecord.objects.count() == 2


def test_ingest_stores_raw_payload_untouched(db):
    payload = make_payload(make_message_event())

    EventService().ingest(payload)

    assert RawEvent.objects.get().payload == payload


def test_duplicate_event_is_counted_not_stored(db):
    payload = make_payload(make_message_event())
    service = EventService()

    service.ingest(payload)
    result = service.ingest(payload)

    assert result == type(result)(created=0, duplicated=1, invalid=0)
    assert BackupRecord.objects.count() == 1


def test_empty_events_list_is_accepted(db):
    """LINE 後台的 Verify 按鈕會送空的 events。"""
    result = EventService().ingest(make_payload())

    assert result.created == 0
    assert RawEvent.objects.count() == 1


def test_unparsable_event_is_counted_as_invalid(db):
    result = EventService().ingest({"events": [{"type": "message"}]})

    assert result.invalid == 1
    assert BackupRecord.objects.count() == 0


def test_non_message_event_is_recorded_without_message_id(db):
    """加入群組之類的事件要記錄下來，但沒有 message id（Edge case 10）。"""
    event = {
        "type": "follow",
        "webhookEventId": "evt-follow",
        "timestamp": 1462629479859,
        "source": {"type": "user", "userId": "U-user-1"},
    }

    EventService().ingest(make_payload(event))

    record = BackupRecord.objects.get()
    assert record.message_type == "follow"
    assert record.line_message_id is None


def test_parse_group_event_uses_group_id():
    event = make_message_event(source_type="group", source_id="G-group-1")

    fields = parse_event(event)

    assert fields["source_type"] == "group"
    assert fields["source_id"] == "G-group-1"
    assert fields["sender_id"] == "U-sender-1"


def test_parse_converts_line_timestamp_to_utc_datetime():
    fields = parse_event(make_message_event(timestamp=1462629479859))

    assert fields["line_timestamp"].tzinfo is timezone.utc
    assert fields["line_timestamp"].year == 2016


def test_parse_uses_now_when_timestamp_missing():
    event = make_message_event()
    del event["timestamp"]

    assert parse_event(event)["line_timestamp"] is not None


@pytest.mark.parametrize(
    "broken_event",
    [
        {"source": {"type": "user", "userId": "U-1"}},  # 缺 webhookEventId
        {"webhookEventId": "evt-1", "source": {"type": "unknown"}},  # 不認得的 source
        {"webhookEventId": "evt-1", "source": {"type": "user"}},  # 缺 userId
        {"webhookEventId": "evt-1"},  # 完全沒有 source
    ],
)
def test_parse_returns_none_for_broken_events(broken_event):
    assert parse_event(broken_event) is None


def test_sticker_message_is_recorded_as_its_own_type(db):
    """不支援的訊息類型不會讓程式壞掉，先記下來再交給 Router（Edge case 9）。"""
    EventService().ingest(make_payload(make_message_event(message_type="sticker")))

    assert BackupRecord.objects.get().message_type == "sticker"
