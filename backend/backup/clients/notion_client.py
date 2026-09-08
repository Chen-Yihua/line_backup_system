"""包住 Notion SDK（docs/architecture.md：Adapter / Wrapper）。

對外只暴露 `append_text()`，並把 SDK 的例外翻譯成 `TransientError` /
`PermanentError`，讓 Service 層不用認得 Notion 的錯誤型別。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from django.conf import settings
from notion_client import Client
from notion_client.errors import APIResponseError, HTTPResponseError, RequestTimeoutError

from backup.errors import PermanentError, TransientError
from backup.utils.text_splitter import make_title, split_text

# Notion database 需要有這些屬性（名稱要一模一樣，見 README 的設定說明）。
TITLE_PROPERTY = "Message"
SENDER_PROPERTY = "Sender"
SOURCE_PROPERTY = "Source"
MESSAGE_ID_PROPERTY = "LINE Message ID"
SENT_AT_PROPERTY = "Sent At"

# 這些 HTTP 狀態重試才有意義：伺服器端問題或被限流。
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class MessageMeta:
    """一則訊息的來源資訊，會存成 Notion 的屬性欄位。"""

    line_message_id: str | None
    source_type: str
    source_id: str
    sender_id: str | None
    sent_at: datetime


class NotionClient:
    """把一則文字訊息寫成 Notion database 裡的一頁。"""

    def __init__(self, token: str | None = None, client: Any = None) -> None:
        """`client` 可注入，測試時塞假的物件就不會真的打網路。"""
        self._client = client or Client(auth=token or settings.NOTION_TOKEN)

    def append_text(self, database_id: str, text: str, meta: MessageMeta) -> str:
        """建立一頁並回傳 page id。

        超過長度上限的文字會被切成多個段落區塊（Edge case 4）。
        """
        chunks = split_text(text)
        if not chunks:
            raise PermanentError("空白文字不應該寫進 Notion")

        try:
            page = self._client.pages.create(
                parent={"database_id": database_id},
                properties=_build_properties(text, meta),
                children=[_paragraph(chunk) for chunk in chunks],
            )
        except (RequestTimeoutError, httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"Notion 連線問題：{type(exc).__name__}") from exc
        except APIResponseError as exc:
            raise _translate_api_error(exc) from exc
        except HTTPResponseError as exc:
            raise TransientError(f"Notion 回應異常：{type(exc).__name__}") from exc

        return page["id"]


def _translate_api_error(exc: APIResponseError) -> TransientError | PermanentError:
    """依 HTTP 狀態決定「值得重試」還是「重試也沒用」。"""
    if exc.status in _TRANSIENT_STATUS:
        return TransientError(f"Notion 暫時性錯誤 status={exc.status}")
    return PermanentError(f"Notion 永久性錯誤 status={exc.status} code={exc.code}")


def _build_properties(text: str, meta: MessageMeta) -> dict[str, Any]:
    """組出 Notion database 的屬性欄位（FR-5 要求的 5 個資訊）。"""
    return {
        TITLE_PROPERTY: {"title": [{"text": {"content": make_title(text)}}]},
        SENDER_PROPERTY: _rich_text(meta.sender_id),
        SOURCE_PROPERTY: _rich_text(f"{meta.source_type}:{meta.source_id}"),
        MESSAGE_ID_PROPERTY: _rich_text(meta.line_message_id),
        SENT_AT_PROPERTY: {"date": {"start": meta.sent_at.isoformat()}},
    }


def _rich_text(value: str | None) -> dict[str, Any]:
    """空值也要送出合法結構，不然 Notion 會回 400。"""
    return {"rich_text": [{"text": {"content": value}}] if value else []}


def _paragraph(content: str) -> dict[str, Any]:
    """一個段落區塊。"""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
    }
