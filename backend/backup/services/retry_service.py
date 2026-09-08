"""背景 worker 的邏輯：領一筆待處理記錄、做備份、決定失敗後怎麼辦。

對應 docs/architecture.md Flow 2 / Flow 3、docs/workflow.md「Retry」。
重點是把「暫時性」跟「永久性」錯誤分開——網路斷線值得重試，
內容已過期重試 100 次結果都一樣，只會拖慢整個 worker。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from django.conf import settings

from backup import repository
from backup.errors import PermanentError, SkipError, TransientError
from backup.models import BackupRecord, BackupStatus
from backup.services.backup_service import BackupRouter

logger = logging.getLogger(__name__)


class RetryService:
    """一次處理一筆 `PENDING` 記錄。"""

    def __init__(
        self,
        router: BackupRouter | None = None,
        repo: Any = repository,
        max_attempts: int | None = None,
    ) -> None:
        """Router、repository、重試上限都可注入，方便測試。"""
        self._router = router or BackupRouter()
        self._repo = repo
        self._max_attempts = max_attempts or settings.MAX_BACKUP_ATTEMPTS

    def run_once(self, exclude_ids: Iterable[int] = ()) -> BackupRecord | None:
        """領一筆記錄處理完；沒有待處理的就回 None。"""
        record = self._repo.claim_next_pending(exclude_ids)
        if record is None:
            return None

        try:
            service = self._router.route(record.message_type)
            service.backup(record)
        except SkipError as exc:
            self._repo.mark_skipped(record, str(exc))
        except PermanentError as exc:
            self._repo.mark_failed(record, str(exc))
        except TransientError as exc:
            self._handle_transient(record, str(exc))
        except Exception as exc:  # noqa: BLE001 - worker 不能被單一筆記錄弄掛
            logger.exception("unexpected backup error", extra={"context": {"record_id": record.pk}})
            self._handle_transient(record, f"未預期的錯誤：{type(exc).__name__}")

        self._log_outcome(record)
        return record

    def run(self, limit: int = 50) -> int:
        """跑一輪，最多處理 `limit` 筆，回傳實際處理數量。

        已經處理過的記錄不會在同一輪再被領一次——暫時性失敗的記錄會被放回
        `PENDING`，那是留給下次排程的，不是這一輪的工作。
        有上限則是為了讓每次排程執行都能在合理時間內結束。
        """
        handled: list[int] = []
        while len(handled) < limit:
            record = self.run_once(exclude_ids=handled)
            if record is None:
                break
            handled.append(record.pk)
        return len(handled)

    def _handle_transient(self, record: BackupRecord, note: str) -> None:
        """還沒用完次數就放回 PENDING，用完了就標記 FAILED（FR-7）。"""
        if record.attempts < self._max_attempts:
            self._repo.mark_for_retry(record, note)
        else:
            self._repo.mark_failed(record, f"重試 {record.attempts} 次仍失敗：{note}")

    @staticmethod
    def _log_outcome(record: BackupRecord) -> None:
        """只記狀態與 id，不記訊息內容（NFR：log 不含個資）。"""
        logger.info(
            "backup processed",
            extra={
                "context": {
                    "record_id": record.pk,
                    "message_type": record.message_type,
                    "status": record.status,
                    "attempts": record.attempts,
                }
            },
        )


def pending_count() -> int:
    """還有幾筆待處理，給管理指令輸出用。"""
    return BackupRecord.objects.filter(status=BackupStatus.PENDING).count()
