"""驗證 `X-Line-Signature`（FR-2、docs/security.md）。

LINE 用 Channel Secret 對 request body 做 HMAC-SHA256、再轉 base64。
這個模組不依賴 Django，也不碰資料庫，方便單獨測試。
"""

import base64
import hashlib
import hmac


def calculate_signature(channel_secret: str, body: bytes) -> str:
    """算出 body 對應的 LINE 簽章（base64 字串）。"""
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def is_valid_signature(channel_secret: str, body: bytes, signature: str | None) -> bool:
    """比對簽章是否正確。

    用 `hmac.compare_digest` 做常數時間比對，避免 timing attack。
    缺少簽章或 secret 沒設定一律視為不合法——寧可拒絕，也不要放行假請求。
    """
    if not signature or not channel_secret:
        return False

    expected = calculate_signature(channel_secret, body)
    return hmac.compare_digest(expected, signature)
