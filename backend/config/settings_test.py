"""測試專用設定。

先把假的外部服務設定塞進環境變數，再載入正式的 `settings`——
這樣測試不需要 `.env`，也不會不小心用到真的 token（NFR：外部 API 全部用假的）。

資料庫本機與正式都用 PostgreSQL，所以跑測試需要一顆本機可連線的 PostgreSQL
（帳密預設抓一般本機安裝的預設值；已經有 `.env`／環境變數設定 `DATABASE_URL`
的話會沿用那個連線，不會被這裡的預設值蓋掉）。Django 會在這顆資料庫底下
自動建立/刪除 `test_<db name>`，不會動到開發用的資料。
"""

import os

os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL", "postgres://postgres:postgres@localhost:5432/line_backup_system"
)
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-channel-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-database-id")
os.environ.setdefault("GOOGLE_OAUTH_TOKEN_FILE", "test-drive-token.json")
os.environ.setdefault("GOOGLE_DRIVE_ROOT_FOLDER_ID", "test-root-folder-id")

from config.settings import *  # noqa: E402,F401,F403
