"""包住 Google Drive API（FR-6）。

對外只暴露「找/建資料夾」與「上傳檔案」兩件事，並把 Google 的例外
翻譯成 `TransientError` / `PermanentError`。
"""

from __future__ import annotations

import io

from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from backup.errors import PermanentError, TransientError

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"

# 這些狀態重試才有意義：限流或 Google 端暫時性問題。
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}

# 支援 Shared Drive（Service Account 沒有自己的 My Drive 容量，見 README 設定說明）。
_SHARED_DRIVE_ARGS = {"supportsAllDrives": True}


class DriveClient:
    """把媒體檔案放進 Drive，依「對話 / 年 / 月」分資料夾。"""

    def __init__(self, service=None, credentials_path: str | None = None) -> None:
        """`service` 可注入，測試時塞假的物件就不會真的打網路。

        真正的 service 到第一次用到才建立——不然只是組個路由表（`BackupRouter`）
        就會因為讀不到金鑰檔而爆炸。
        """
        self._service = service
        self._credentials_path = credentials_path

    @property
    def service(self):
        """延遲建立 Drive API service。"""
        if self._service is None:
            path = self._credentials_path
            if path is None:
                path = settings.GOOGLE_APPLICATION_CREDENTIALS
            self._service = _build_service(path)
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
            self.service.files().create(
                body=body, media_body=media, fields="id", **_SHARED_DRIVE_ARGS
            )
        )
        return created["id"]

    def _find_or_create_folder(self, parent_id: str, name: str) -> str:
        """同名資料夾已存在就沿用，不重複建立。"""
        existing = self._find_folder(parent_id, name)
        if existing is not None:
            return existing

        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        created = self._execute(
            self.service.files().create(body=body, fields="id", **_SHARED_DRIVE_ARGS)
        )
        return created["id"]

    def _find_folder(self, parent_id: str, name: str) -> str | None:
        """在指定父資料夾底下找同名資料夾。"""
        query = (
            f"name = '{_escape(name)}' and mimeType = '{FOLDER_MIME}' "
            f"and '{_escape(parent_id)}' in parents and trashed = false"
        )
        result = self._execute(
            self.service.files().list(
                q=query,
                fields="files(id)",
                pageSize=1,
                includeItemsFromAllDrives=True,
                **_SHARED_DRIVE_ARGS,
            )
        )
        files = result.get("files") or []
        return files[0]["id"] if files else None

    @staticmethod
    def _execute(request):
        """統一執行請求並翻譯例外，避免每個方法都寫一次 try/except。"""
        try:
            return request.execute()
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except (TimeoutError, OSError) as exc:
            raise TransientError(f"Drive 連線問題：{type(exc).__name__}") from exc


def _build_service(credentials_path: str):
    """用 Service Account 金鑰建立 Drive API service。"""
    if not credentials_path:
        raise PermanentError("沒有設定 GOOGLE_APPLICATION_CREDENTIALS")

    credentials = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=DRIVE_SCOPES
    )
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
