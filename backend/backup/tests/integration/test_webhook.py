"""Webhook 整合測試：HTTP 請求 → 資料庫（UC-1 ~ UC-4）。"""

import json

import pytest
from django.urls import reverse

from backup.models import BackupRecord, BackupStatus, RawEvent
from backup.tests.conftest import make_message_event, make_payload, sign

pytestmark = pytest.mark.django_db


def post(client, body: bytes, signature: str | None):
    """送出一個 Webhook 請求。"""
    headers = {"HTTP_X_LINE_SIGNATURE": signature} if signature is not None else {}
    return client.post(
        reverse("line-webhook"), data=body, content_type="application/json", **headers
    )


def test_valid_request_stores_pending_record(client, line_secret):
    body, signature = sign(make_payload(make_message_event()))

    response = post(client, body, signature)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    record = BackupRecord.objects.get()
    assert record.status == BackupStatus.PENDING
    assert record.webhook_event_id == "evt-1"
    assert record.message_type == "text"


def test_invalid_signature_is_rejected_and_stores_nothing(client, line_secret):
    body, _ = sign(make_payload(make_message_event()))

    response = post(client, body, "wrong-signature")

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_signature"}
    assert RawEvent.objects.count() == 0
    assert BackupRecord.objects.count() == 0


def test_missing_signature_header_is_rejected(client, line_secret):
    body, _ = sign(make_payload(make_message_event()))

    response = post(client, body, None)

    assert response.status_code == 401
    assert RawEvent.objects.count() == 0


def test_duplicate_event_returns_200_without_second_record(client, line_secret):
    """LINE 重送同一個事件（UC-3）。"""
    body, signature = sign(make_payload(make_message_event()))

    first = post(client, body, signature)
    second = post(client, body, signature)

    assert (first.status_code, second.status_code) == (200, 200)
    assert BackupRecord.objects.count() == 1
    assert RawEvent.objects.count() == 2  # 原始資料仍如實保留兩份


def test_empty_events_returns_200(client, line_secret):
    """LINE 後台按 Verify 時會送空的 events。"""
    body, signature = sign(make_payload())

    response = post(client, body, signature)

    assert response.status_code == 200
    assert BackupRecord.objects.count() == 0


def test_malformed_json_returns_400(client, line_secret):
    from backup.utils.signature import calculate_signature

    body = b"{not json"
    response = post(client, body, calculate_signature(line_secret, body))

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_payload"}
    assert RawEvent.objects.count() == 0


def test_non_object_json_returns_400(client, line_secret):
    from backup.utils.signature import calculate_signature

    body = json.dumps([1, 2, 3]).encode("utf-8")
    response = post(client, body, calculate_signature(line_secret, body))

    assert response.status_code == 400


def test_database_failure_returns_500_so_line_retries(client, line_secret, monkeypatch):
    """存檔失敗要回 500 讓 LINE 重送，不能假裝收到了。"""
    from django.db import DatabaseError

    from backup import repository

    def boom(*args, **kwargs):
        raise DatabaseError("connection lost")

    monkeypatch.setattr(repository, "create_raw_event", boom)

    body, signature = sign(make_payload(make_message_event()))
    response = post(client, body, signature)

    assert response.status_code == 500
    assert response.json() == {"error": "internal_error"}


def test_multiple_events_in_one_request(client, line_secret):
    body, signature = sign(
        make_payload(
            make_message_event(webhook_event_id="evt-1", message_id="msg-1"),
            make_message_event(webhook_event_id="evt-2", message_id="msg-2", message_type="image"),
            make_message_event(
                webhook_event_id="evt-3", message_id="msg-3", message_type="sticker"
            ),
        )
    )

    response = post(client, body, signature)

    assert response.status_code == 200
    assert BackupRecord.objects.count() == 3
    assert set(BackupRecord.objects.values_list("message_type", flat=True)) == {
        "text",
        "image",
        "sticker",
    }
