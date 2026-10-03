"""`authorize_drive` 指令測試——不會真的開瀏覽器，也不會打 Google Drive。"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from backup.clients import drive_client
from backup.clients.drive_client import DriveClient, load_credentials
from backup.errors import PermanentError
from backup.management.commands.authorize_drive import DEFAULT_FOLDER_NAME, MY_DRIVE_ROOT
from backup.tests.unit.test_drive_client import FakeFiles, FakeService, make_credentials


@pytest.fixture
def fake_drive(monkeypatch):
    """把 OAuth 流程與 Drive service 換成假的，回傳假的 files() 方便檢查。"""
    files = FakeFiles()
    monkeypatch.setattr(drive_client, "run_oauth_flow", lambda path: make_credentials())
    monkeypatch.setattr(
        DriveClient, "from_credentials", classmethod(lambda cls, c: cls(service=FakeService(files)))
    )
    return files


@pytest.fixture
def token_path(tmp_path, settings):
    path = tmp_path / "drive-token.json"
    settings.GOOGLE_OAUTH_TOKEN_FILE = str(path)
    return path


def run(*args) -> str:
    out = StringIO()
    call_command("authorize_drive", "client_secret.json", *args, stdout=out)
    return out.getvalue()


def test_saves_token_and_prints_root_folder_id(fake_drive, token_path):
    output = run()

    assert load_credentials(str(token_path)).refresh_token == "refresh-token"
    assert f"GOOGLE_DRIVE_ROOT_FOLDER_ID=new-{DEFAULT_FOLDER_NAME}" in output


def test_root_folder_is_created_in_my_drive(fake_drive, token_path):
    run("--folder-name", "My Backup")

    assert fake_drive.created[0]["name"] == "My Backup"
    assert fake_drive.created[0]["parents"] == [MY_DRIVE_ROOT]


def test_rerun_reuses_existing_root_folder(fake_drive, token_path):
    """重跑不會多建一個同名資料夾。"""
    fake_drive.existing_folders = {DEFAULT_FOLDER_NAME: "existing-root"}

    output = run()

    assert fake_drive.created == []
    assert "GOOGLE_DRIVE_ROOT_FOLDER_ID=existing-root" in output


def test_missing_token_setting_stops_before_authorizing(fake_drive, settings):
    settings.GOOGLE_OAUTH_TOKEN_FILE = ""

    with pytest.raises(CommandError, match="GOOGLE_OAUTH_TOKEN_FILE"):
        run()


def test_flow_error_becomes_command_error(monkeypatch, token_path):
    def broken_flow(path):
        raise PermanentError("找不到 OAuth 用戶端檔案")

    monkeypatch.setattr(drive_client, "run_oauth_flow", broken_flow)

    with pytest.raises(CommandError, match="OAuth"):
        run()
