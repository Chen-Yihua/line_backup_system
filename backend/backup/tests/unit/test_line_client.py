"""LineClient 測試（Edge case 6）——不會真的打 LINE。"""

import pytest
import requests

from backup.clients.line_client import LineClient
from backup.errors import PermanentError, TransientError


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", content_type: str | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type} if content_type else {}


class FakeSession:
    """記下請求內容，或依設定丟出例外。"""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def get(self, url, headers=None, timeout=None):
        if self.error:
            raise self.error
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.response


def test_downloads_content_and_type():
    session = FakeSession(FakeResponse(200, b"binary-data", "image/png"))

    content = LineClient(access_token="token", session=session).download_content("msg-1")

    assert content.data == b"binary-data"
    assert content.content_type == "image/png"


def test_sends_bearer_token_and_timeout():
    session = FakeSession(FakeResponse(200, b"x", "image/png"))

    LineClient(access_token="token", session=session).download_content("msg-1")

    assert session.calls[0]["headers"]["Authorization"] == "Bearer token"
    assert session.calls[0]["timeout"] > 0
    assert session.calls[0]["url"].endswith("/msg-1/content")


def test_missing_content_type_falls_back_to_octet_stream():
    session = FakeSession(FakeResponse(200, b"x"))

    content = LineClient(access_token="token", session=session).download_content("msg-1")

    assert content.content_type == "application/octet-stream"


@pytest.mark.parametrize("status", [404, 410, 403])
def test_expired_or_missing_content_is_permanent(status):
    """內容過期重試也沒用，直接標記失敗（Edge case 6）。"""
    session = FakeSession(FakeResponse(status))

    with pytest.raises(PermanentError):
        LineClient(access_token="token", session=session).download_content("msg-1")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_side_errors_are_transient(status):
    session = FakeSession(FakeResponse(status))

    with pytest.raises(TransientError):
        LineClient(access_token="token", session=session).download_content("msg-1")


def test_timeout_is_transient():
    session = FakeSession(error=requests.Timeout())

    with pytest.raises(TransientError):
        LineClient(access_token="token", session=session).download_content("msg-1")


def test_connection_error_is_transient():
    session = FakeSession(error=requests.ConnectionError())

    with pytest.raises(TransientError):
        LineClient(access_token="token", session=session).download_content("msg-1")
