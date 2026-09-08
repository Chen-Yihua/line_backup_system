"""NotionClient 測試（Edge case 4、7）——不會真的打 Notion。"""

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from notion_client.errors import APIResponseError, RequestTimeoutError

from backup.clients.notion_client import (
    MESSAGE_ID_PROPERTY,
    TITLE_PROPERTY,
    MessageMeta,
    NotionClient,
)
from backup.errors import PermanentError, TransientError
from backup.utils.text_splitter import NOTION_TEXT_LIMIT

META = MessageMeta(
    line_message_id="msg-1",
    source_type="user",
    source_id="U-user-1",
    sender_id="U-user-1",
    sent_at=datetime(2026, 5, 7, 12, 30, tzinfo=timezone.utc),
)


class FakePages:
    """記下呼叫參數，或依設定丟出例外。"""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        if self.error:
            raise self.error
        self.calls.append(kwargs)
        return {"id": "page-123"}


def make_client(error: Exception | None = None) -> tuple[NotionClient, FakePages]:
    pages = FakePages(error)
    return NotionClient(client=SimpleNamespace(pages=pages)), pages


def api_error(status: int) -> APIResponseError:
    return APIResponseError(
        code="internal_server_error",
        status=status,
        message="boom",
        headers=httpx.Headers(),
        raw_body_text="{}",
    )


def test_creates_page_and_returns_id():
    client, pages = make_client()

    page_id = client.append_text("db-1", "hello", META)

    assert page_id == "page-123"
    assert pages.calls[0]["parent"] == {"database_id": "db-1"}


def test_writes_metadata_into_properties():
    client, pages = make_client()

    client.append_text("db-1", "hello", META)
    properties = pages.calls[0]["properties"]

    assert properties[TITLE_PROPERTY]["title"][0]["text"]["content"] == "hello"
    assert properties[MESSAGE_ID_PROPERTY]["rich_text"][0]["text"]["content"] == "msg-1"


def test_missing_sender_still_produces_valid_property():
    client, pages = make_client()

    client.append_text("db-1", "hello", MessageMeta(None, "user", "U-1", None, META.sent_at))

    assert pages.calls[0]["properties"]["Sender"]["rich_text"] == []


def test_long_text_becomes_multiple_blocks():
    client, pages = make_client()

    client.append_text("db-1", "a" * (NOTION_TEXT_LIMIT + 1), META)

    assert len(pages.calls[0]["children"]) == 2


def test_blank_text_is_rejected_before_calling_notion():
    client, pages = make_client()

    with pytest.raises(PermanentError):
        client.append_text("db-1", "   ", META)

    assert pages.calls == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_side_errors_are_transient(status):
    client, _ = make_client(api_error(status))

    with pytest.raises(TransientError):
        client.append_text("db-1", "hello", META)


@pytest.mark.parametrize("status", [400, 401, 404])
def test_client_side_errors_are_permanent(status):
    client, _ = make_client(api_error(status))

    with pytest.raises(PermanentError):
        client.append_text("db-1", "hello", META)


def test_timeout_is_transient():
    client, _ = make_client(RequestTimeoutError())

    with pytest.raises(TransientError):
        client.append_text("db-1", "hello", META)


def test_network_error_is_transient():
    client, _ = make_client(httpx.ConnectError("no route to host"))

    with pytest.raises(TransientError):
        client.append_text("db-1", "hello", META)
