"""備份流程共用的錯誤分類。

Retry 流程只看兩件事：這個錯誤重試有沒有意義（見 docs/workflow.md「Retry」）。
所以 Client 層負責把各家 SDK 的例外翻譯成這兩種，Service 層就不用認得
`notion_client.APIResponseError` 或 `googleapiclient.errors.HttpError`。
"""


class BackupError(Exception):
    """備份流程的基底錯誤。"""


class TransientError(BackupError):
    """暫時性錯誤（timeout、5xx、網路問題）——值得重試。"""


class PermanentError(BackupError):
    """永久性錯誤（內容過期、權限不足、格式錯誤）——重試也沒用。"""


class SkipError(BackupError):
    """不符合備份條件（檔案太大、空白訊息、不支援的類型）——標記 SKIPPED，不算失敗。"""
