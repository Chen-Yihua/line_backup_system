"""測試共用的 fixture 與假資料產生器。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from backup.models import BackupRecord, RawEvent
from backup.utils.signature import calculate_signature

TEST_CHANNEL_SECRET = "test-channel-secret"


def make_message_event(
    *,
    webhook_event_id: str = "evt-1",
    message_id: str = "msg-1",
    message_type: str = "text",
    text: str = "hello",
    source_type: str = "user",
    source_id: str = "U-user-1",
    timestamp: int = 1462629479859,
    extra_message_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """組出一個 LINE message 事件（格式見 docs/api.md）。"""
    message: dict[str, Any] = {"id": message_id, "type": message_type}
    if message_type == "text":
        message["text"] = text
    if extra_message_fields:
        message.update(extra_message_fields)

    source = {"type": source_type}
    source[{"user": "userId", "group": "groupId", "room": "roomId"}[source_type]] = source_id
    if source_type != "user":
        source["userId"] = "U-sender-1"

    return {
        "type": "message",
        "webhookEventId": webhook_event_id,
        "timestamp": timestamp,
        "source": source,
        "deliveryContext": {"isRedelivery": False},
        "message": message,
    }


def make_payload(*events: dict[str, Any]) -> dict[str, Any]:
    """把事件包成一次 Webhook 請求的 body。"""
    return {"destination": "U-destination", "events": list(events)}


def sign(payload: dict[str, Any], secret: str = TEST_CHANNEL_SECRET) -> tuple[bytes, str]:
    """回傳 (body bytes, 對應的合法簽章)。"""
    body = json.dumps(payload).encode("utf-8")
    return body, calculate_signature(secret, body)


@pytest.fixture
def line_secret(settings) -> str:
    """確保測試用的 channel secret 一致。"""
    settings.LINE_CHANNEL_SECRET = TEST_CHANNEL_SECRET
    return TEST_CHANNEL_SECRET


@pytest.fixture
def raw_event(db) -> RawEvent:
    """一筆已存好的原始事件，內含一則文字訊息。"""
    return RawEvent.objects.create(payload=make_payload(make_message_event()))


@pytest.fixture
def text_record(raw_event: RawEvent) -> BackupRecord:
    """一筆待處理的文字訊息記錄。"""
    return BackupRecord.objects.create(
        raw_event=raw_event,
        webhook_event_id="evt-1",
        line_message_id="msg-1",
        source_type="user",
        source_id="U-user-1",
        sender_id="U-user-1",
        message_type="text",
        line_timestamp=datetime(2026, 5, 7, 12, 30, tzinfo=timezone.utc),
    )


def make_record(raw_event: RawEvent, **overrides: Any) -> BackupRecord:
    """建立一筆 BackupRecord，欄位可覆寫。"""
    fields: dict[str, Any] = {
        "raw_event": raw_event,
        "webhook_event_id": "evt-1",
        "line_message_id": "msg-1",
        "source_type": "user",
        "source_id": "U-user-1",
        "sender_id": "U-user-1",
        "message_type": "text",
        "line_timestamp": datetime(2026, 5, 7, 12, 30, tzinfo=timezone.utc),
    }
    fields.update(overrides)
    return BackupRecord.objects.create(**fields)
