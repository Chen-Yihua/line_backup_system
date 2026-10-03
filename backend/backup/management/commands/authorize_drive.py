"""一次性的 Google Drive 授權（docs/architecture.md「Google Drive 的認證方式」）。

用法：
    python manage.py authorize_drive secrets/client_secret.json [--folder-name NAME]

做三件事：
1. 印出授權網址，使用者在瀏覽器登入並同意。
2. 把 token 存到 `GOOGLE_OAUTH_TOKEN_FILE`（之後 worker 都讀這個檔）。
3. 在使用者的 Drive 建立備份根資料夾，印出資料夾 ID 給 `GOOGLE_DRIVE_ROOT_FOLDER_ID`。

根資料夾一定要由程式建立：權限只有 `drive.file`，程式看不到使用者自己建的資料夾。
重跑是安全的——同名資料夾已存在就沿用，token 檔會被新的覆蓋。
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backup.clients import drive_client
from backup.clients.drive_client import DriveClient
from backup.errors import PermanentError, TransientError

DEFAULT_FOLDER_NAME = "LINE Message Archive"
# Drive 用 "root" 代表使用者的「我的雲端硬碟」最上層。
MY_DRIVE_ROOT = "root"


class Command(BaseCommand):
    """授權 Google Drive 並建立備份根資料夾。"""

    help = "Google Drive OAuth 授權（只需要做一次），並建立備份根資料夾"

    def add_arguments(self, parser) -> None:
        """OAuth 用戶端檔案只有授權時用得到，所以用參數傳，不放進設定。"""
        parser.add_argument("client_secrets", help="Google Cloud 下載的 OAuth 用戶端 JSON 檔")
        parser.add_argument(
            "--folder-name",
            default=DEFAULT_FOLDER_NAME,
            help=f"備份根資料夾名稱（預設「{DEFAULT_FOLDER_NAME}」）",
        )

    def handle(self, *args, **options) -> None:
        """授權 → 存 token → 建資料夾。"""
        token_path = settings.GOOGLE_OAUTH_TOKEN_FILE
        if not token_path:
            raise CommandError("請先在 .env 設定 GOOGLE_OAUTH_TOKEN_FILE（token 要存在哪）")

        try:
            credentials = drive_client.run_oauth_flow(options["client_secrets"])
            drive_client.save_credentials(credentials, token_path)
            folder_id = DriveClient.from_credentials(credentials).ensure_folder_path(
                MY_DRIVE_ROOT, [options["folder_name"]]
            )
        except (PermanentError, TransientError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"授權完成，token 已存到 {token_path}"))
        self.stdout.write(f"把這行填進 .env：\nGOOGLE_DRIVE_ROOT_FOLDER_ID={folder_id}")
