"""DriveClient 測試（Edge case 8）——不會真的打 Google Drive。"""

import httplib2
import pytest
from googleapiclient.errors import HttpError

from backup.clients.drive_client import FOLDER_MIME, DriveClient
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


def test_missing_credentials_path_is_permanent():
    """建構時不碰金鑰，第一次真的要用才報錯（讓組路由表不會爆炸）。"""
    client = DriveClient(credentials_path="")

    with pytest.raises(PermanentError):
        _ = client.service
