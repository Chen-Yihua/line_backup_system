"""背景 worker 的進入點（docs/architecture.md Flow 2）。

用法：
    python manage.py process_pending_backups [--limit N]

由排程（本機用 cron、正式環境用 Cloud Scheduler）定期呼叫。
"""

from django.core.management.base import BaseCommand

from backup.services.retry_service import RetryService, pending_count


class Command(BaseCommand):
    """處理 `PENDING` 的備份記錄。"""

    help = "處理待備份的 BackupRecord（文字 → Notion、媒體 → Google Drive）"

    def add_arguments(self, parser) -> None:
        """`--limit` 避免單次執行跑太久。"""
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="這一輪最多處理幾筆（預設 50）",
        )

    def handle(self, *args, **options) -> None:
        """跑一輪並輸出結果。"""
        limit: int = options["limit"]
        processed = RetryService().run(limit=limit)

        self.stdout.write(self.style.SUCCESS(f"處理 {processed} 筆，仍待處理 {pending_count()} 筆"))
