"""Django settings.

所有密鑰與外部服務設定一律從環境變數讀取（FR-10），不寫死在程式裡。
正式環境（DEBUG=False）啟動時會檢查必要變數是否齊全，缺少就直接報錯，
避免部署後才在背景 worker 裡爆炸。
"""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    MAX_BACKUP_ATTEMPTS=(int, 3),
    MAX_MEDIA_FILE_SIZE_MB=(int, 50),
)

# .env 只在本機開發使用；正式環境靠平台注入環境變數。
_ENV_FILE = PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    env.read_env(str(_ENV_FILE))

DEBUG = env("DEBUG")
SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key" if DEBUG else None)
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "backup",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# 系統沒有使用者概念（唯一的入口靠 LINE 簽章驗證），所以不裝 django.contrib.auth，
# 也要告訴 DRF 不要去找 AnonymousUser。
REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

DATABASES = {"default": env.db_url("DATABASE_URL")}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# --- 安全性（見 docs/security.md：HTTPS Only）---
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# --- 外部服務設定 ---
LINE_CHANNEL_SECRET = env("LINE_CHANNEL_SECRET", default="")
LINE_CHANNEL_ACCESS_TOKEN = env("LINE_CHANNEL_ACCESS_TOKEN", default="")

NOTION_TOKEN = env("NOTION_TOKEN", default="")
NOTION_DATABASE_ID = env("NOTION_DATABASE_ID", default="")

GOOGLE_APPLICATION_CREDENTIALS = env("GOOGLE_APPLICATION_CREDENTIALS", default="")
GOOGLE_DRIVE_ROOT_FOLDER_ID = env("GOOGLE_DRIVE_ROOT_FOLDER_ID", default="")

# --- 備份行為（FR-7 固定重試 3 次、Edge case 5 檔案大小上限）---
MAX_BACKUP_ATTEMPTS = env("MAX_BACKUP_ATTEMPTS")
MAX_MEDIA_FILE_SIZE_MB = env("MAX_MEDIA_FILE_SIZE_MB")

REQUIRED_SETTINGS = (
    "LINE_CHANNEL_SECRET",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "NOTION_TOKEN",
    "NOTION_DATABASE_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_DRIVE_ROOT_FOLDER_ID",
)

if not DEBUG:
    _missing = [name for name in REQUIRED_SETTINGS if not globals()[name]]
    if _missing:
        raise ImproperlyConfigured(
            "缺少必要的環境變數：" + ", ".join(_missing) + "（見 .env.example）"
        )

# --- Log（NFR：結構化 JSON log，不含個資或密鑰）---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "backup.utils.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"backup": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
