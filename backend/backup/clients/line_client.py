"""包住 LINE Content API（FR-6 的第一步：把媒體內容抓下來）。

只用 `requests`，不裝 LINE SDK——需要的就這一支 endpoint，
多一個依賴不划算（見 CLAUDE.md「Simplicity First」）。
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings

from backup.errors import PermanentError, TransientError

CONTENT_URL_TEMPLATE = "https://api-data.line.me/v2/bot/message/{message_id}/content"
DEFAULT_TIMEOUT_SECONDS = 30

# 內容已過期或訊息不存在，重試 100 次結果都一樣（Edge case 6）。
_PERMANENT_STATUS = {400, 401, 403, 404, 410}


@dataclass(frozen=True)
class DownloadedContent:
    """從 LINE 下載回來的原始內容。"""

    data: bytes
    content_type: str


class LineClient:
    """呼叫 LINE Messaging API。"""

    def __init__(self, access_token: str | None = None, session: requests.Session | None = None):
        """`session` 可注入，測試時塞假的物件就不會真的打網路。"""
        self._access_token = access_token or settings.LINE_CHANNEL_ACCESS_TOKEN
        self._session = session or requests.Session()

    def download_content(self, message_id: str) -> DownloadedContent:
        """下載一則媒體訊息的內容。"""
        url = CONTENT_URL_TEMPLATE.format(message_id=message_id)
        headers = {"Authorization": f"Bearer {self._access_token}"}

        try:
            response = self._session.get(url, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS)
        except requests.Timeout as exc:
            raise TransientError("LINE 下載逾時") from exc
        except requests.RequestException as exc:
            raise TransientError(f"LINE 連線問題：{type(exc).__name__}") from exc

        _raise_for_status(response.status_code)

        return DownloadedContent(
            data=response.content,
            content_type=response.headers.get("Content-Type", "application/octet-stream"),
        )


def _raise_for_status(status_code: int) -> None:
    """把 HTTP 狀態翻譯成可重試 / 不可重試的錯誤。"""
    if status_code in _PERMANENT_STATUS:
        raise PermanentError(f"LINE 內容取不到 status={status_code}")
    if status_code >= 400:
        raise TransientError(f"LINE 暫時性錯誤 status={status_code}")
