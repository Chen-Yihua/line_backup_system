"""DriveClient 測試（Edge case 8）——不會真的打 Google Drive。"""

import stat

import httplib2
import pytest
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from backup.clients.drive_client import (
    DRIVE_SCOPES,
    FOLDER_MIME,
    DriveClient,
    load_credentials,
    run_oauth_flow,
    save_credentials,
)
from backup.errors import PermanentError, TransientError


class FakeRequest:
    def __init__(self, result, error: Exception | None = None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class FakeFiles:
    """模擬 Drive 的 files() 資源。"""

    def __init__(self, existing_folders: dict[str, str] | None = None, error=None):
        self.existing_folders = existing_folders or {}
        self.error = error
        self.created: list[dict] = []
        self.queries: list[str] = []

    def list(self, q, **kwargs):
        self.queries.append(q)
        if self.error:
            return FakeRequest(None, self.error)
        for name, folder_id in self.existing_folders.items():
            if f"name = '{name}'" in q:
                return FakeRequest({"files": [{"id": folder_id}]})
        return FakeRequest({"files": []})

    def create(self, body, media_body=None, **kwargs):
        if self.error:
            return FakeRequest(None, self.error)
        self.created.append(body)
        return FakeRequest({"id": f"new-{body['name']}"})


class FakeService:
    def __init__(self, files: FakeFiles):
        self._files = files

    def files(self):
        return self._files


def http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def test_creates_missing_folders_in_order():
    files = FakeFiles()
    client = DriveClient(service=FakeService(files))

    folder_id = client.ensure_folder_path("root", ["U-user-1", "2026", "05"])

    assert [body["name"] for body in files.created] == ["U-user-1", "2026", "05"]
    assert all(body["mimeType"] == FOLDER_MIME for body in files.created)
    assert folder_id == "new-05"


def test_reuses_existing_folder():
    files = FakeFiles(existing_folders={"U-user-1": "existing-folder"})
    client = DriveClient(service=FakeService(files))

    client.ensure_folder_path("root", ["U-user-1"])

    assert files.created == []


def test_upload_returns_file_id():
    files = FakeFiles()
    client = DriveClient(service=FakeService(files))

    file_id = client.upload("folder-1", "photo.png", b"\x89PNG", "image/png")

    assert file_id == "new-photo.png"
    assert files.created[0]["parents"] == ["folder-1"]


def test_folder_name_with_quote_is_escaped():
    files = FakeFiles()
    client = DriveClient(service=FakeService(files))

    client.ensure_folder_path("root", ["it's"])

    assert "it\\'s" in files.queries[0]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_side_errors_are_transient(status):
    client = DriveClient(service=FakeService(FakeFiles(error=http_error(status))))

    with pytest.raises(TransientError):
        client.upload("folder-1", "a.png", b"x", "image/png")


@pytest.mark.parametrize("status", [403, 404])
def test_client_side_errors_are_permanent(status):
    client = DriveClient(service=FakeService(FakeFiles(error=http_error(status))))

    with pytest.raises(PermanentError):
        client.upload("folder-1", "a.png", b"x", "image/png")


def test_network_error_is_transient():
    client = DriveClient(service=FakeService(FakeFiles(error=TimeoutError())))

    with pytest.raises(TransientError):
        client.upload("folder-1", "a.png", b"x", "image/png")


def make_credentials() -> Credentials:
    """授權完會拿到的那種 credentials（假的值，不會拿去打 Google）。"""
    return Credentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=DRIVE_SCOPES,
    )


def test_revoked_authorization_is_permanent():
    """refresh token 被撤銷，重試也沒用，要人重新授權。"""
    client = DriveClient(service=FakeService(FakeFiles(error=RefreshError("invalid_grant"))))

    with pytest.raises(PermanentError, match="authorize_drive"):
        client.upload("folder-1", "a.png", b"x", "image/png")


def test_token_refresh_network_error_is_transient():
    client = DriveClient(service=FakeService(FakeFiles(error=TransportError("dns"))))

    with pytest.raises(TransientError):
        client.upload("folder-1", "a.png", b"x", "image/png")


def test_missing_token_setting_is_permanent():
    """建構時不碰 token，第一次真的要用才報錯（讓組路由表不會爆炸）。"""
    client = DriveClient(token_path="")

    with pytest.raises(PermanentError):
        _ = client.service


def test_missing_token_file_tells_user_to_authorize(tmp_path):
    with pytest.raises(PermanentError, match="authorize_drive"):
        load_credentials(str(tmp_path / "nope.json"))


def test_saved_token_can_be_loaded_back(tmp_path):
    token_path = tmp_path / "secrets" / "drive-token.json"

    save_credentials(make_credentials(), str(token_path))
    loaded = load_credentials(str(token_path))

    assert loaded.refresh_token == "refresh-token"
    assert loaded.client_id == "client-id"


def test_saved_token_is_only_readable_by_owner(tmp_path):
    """token 等同 Drive 的存取權，別的使用者不能讀。"""
    token_path = tmp_path / "drive-token.json"

    save_credentials(make_credentials(), str(token_path))

    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_oauth_flow_with_missing_client_file_is_permanent(tmp_path):
    with pytest.raises(PermanentError, match="OAuth"):
        run_oauth_flow(str(tmp_path / "client_secret.json"))
