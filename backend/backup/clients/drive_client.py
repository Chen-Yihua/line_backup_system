"""包住 Google Drive API（FR-6）。

對外只暴露「找/建資料夾」與「上傳檔案」兩件事，並把 Google 的例外
翻譯成 `TransientError` / `PermanentError`。
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from django.conf import settings
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from backup.errors import PermanentError, TransientError

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"

# 這些狀態重試才有意義：限流或 Google 端暫時性問題。
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}

# token 檔裡有 refresh token，等同 Drive 的存取權：只有自己能讀寫。
_TOKEN_FILE_MODE = 0o600


class DriveClient:
    """把媒體檔案放進 Drive，依「對話 / 年 / 月」分資料夾。"""

    def __init__(self, service=None, token_path: str | None = None) -> None:
        """`service` 可注入，測試時塞假的物件就不會真的打網路。

        真正的 service 到第一次用到才建立——不然只是組個路由表（`BackupRouter`）
        就會因為讀不到 token 檔而爆炸。
        """
        self._service = service
        self._token_path = token_path

    @classmethod
    def from_credentials(cls, credentials: Credentials) -> DriveClient:
        """用剛授權完的 credentials 建立（`authorize_drive` 指令用）。"""
        return cls(service=_build_service(credentials))

    @property
    def service(self):
        """延遲建立 Drive API service。"""
        if self._service is None:
            path = self._token_path
            if path is None:
                path = settings.GOOGLE_OAUTH_TOKEN_FILE
            self._service = _build_service(load_credentials(path))
        return self._service

    def ensure_folder_path(self, root_folder_id: str, names: list[str]) -> str:
        """依序往下找/建資料夾，回傳最底層那個的 id。"""
        parent_id = root_folder_id
        for name in names:
            parent_id = self._find_or_create_folder(parent_id, name)
        return parent_id

    def upload(self, folder_id: str, filename: str, data: bytes, mime_type: str) -> str:
        """上傳檔案，回傳 Drive file id。"""
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        body = {"name": filename, "parents": [folder_id]}

        created = self._execute(
            self.service.files().create(body=body, media_body=media, fields="id")
        )
        return created["id"]

    def _find_or_create_folder(self, parent_id: str, name: str) -> str:
        """同名資料夾已存在就沿用，不重複建立。"""
        existing = self._find_folder(parent_id, name)
        if existing is not None:
            return existing

        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        created = self._execute(self.service.files().create(body=body, fields="id"))
        return created["id"]

    def _find_folder(self, parent_id: str, name: str) -> str | None:
        """在指定父資料夾底下找同名資料夾。"""
        query = (
            f"name = '{_escape(name)}' and mimeType = '{FOLDER_MIME}' "
            f"and '{_escape(parent_id)}' in parents and trashed = false"
        )
        result = self._execute(self.service.files().list(q=query, fields="files(id)", pageSize=1))
        files = result.get("files") or []
        return files[0]["id"] if files else None

    @staticmethod
    def _execute(request):
        """統一執行請求並翻譯例外，避免每個方法都寫一次 try/except。"""
        try:
            return request.execute()
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except RefreshError as exc:
            # refresh token 被撤銷或失效，重試幾次都一樣，要人重新授權。
            raise PermanentError("Drive 授權失效，請重新執行 authorize_drive") from exc
        except (TimeoutError, OSError, TransportError) as exc:
            raise TransientError(f"Drive 連線問題：{type(exc).__name__}") from exc


def load_credentials(token_path: str) -> Credentials:
    """讀 `authorize_drive` 存下來的 token 檔。

    access token 過期時 google-auth 會用 refresh token 自動換新的，
    新的 access token 只留在記憶體——refresh token 不會變，不用寫回檔案。
    """
    if not token_path:
        raise PermanentError("沒有設定 GOOGLE_OAUTH_TOKEN_FILE")
    if not Path(token_path).is_file():
        raise PermanentError("找不到 Drive token 檔，請先執行 authorize_drive")
    return Credentials.from_authorized_user_file(token_path, DRIVE_SCOPES)


def run_oauth_flow(client_secrets_path: str) -> Credentials:
    """跑一次 OAuth 授權：印出網址讓使用者在瀏覽器同意，回傳拿到的 credentials。

    `open_browser=False`：在 WSL / 遠端主機上開不了瀏覽器，改成印網址讓人自己貼。
    redirect 回 localhost，WSL2 會把 Windows 的 localhost 轉進來。
    """
    if not Path(client_secrets_path).is_file():
        raise PermanentError(f"找不到 OAuth 用戶端檔案：{client_secrets_path}")
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, DRIVE_SCOPES)
    return flow.run_local_server(port=0, open_browser=False)


def save_credentials(credentials: Credentials, token_path: str) -> None:
    """把授權結果寫成 token 檔，權限設成只有自己能讀寫。"""
    path = Path(token_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _TOKEN_FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(credentials.to_json())
    path.chmod(_TOKEN_FILE_MODE)


def _build_service(credentials: Credentials):
    """用 OAuth credentials 建立 Drive API service。"""
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _translate_http_error(exc: HttpError) -> TransientError | PermanentError:
    """依 HTTP 狀態決定「值得重試」還是「重試也沒用」。"""
    status_code = getattr(exc.resp, "status", None)
    if status_code in _TRANSIENT_STATUS:
        return TransientError(f"Drive 暫時性錯誤 status={status_code}")
    return PermanentError(f"Drive 永久性錯誤 status={status_code}")


def _escape(value: str) -> str:
    """Drive 查詢語法用單引號包字串，內容裡的引號要跳脫。"""
    return value.replace("\\", "\\\\").replace("'", "\\'")
