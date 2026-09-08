"""資料表定義（見 docs/database.md）。

`RawEvent` 是原始 Webhook 的稽核副本，`BackupRecord` 是實際要處理、
有狀態、可重試的工作項目。Model 只放欄位定義與少量常數，
所有商業邏輯都在 services/ 裡（見 docs/architecture.md）。
"""

from django.db import models


class RawEvent(models.Model):
    """LINE 送來的完整原始 Webhook 內容，不做任何加工。"""

    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "raw_event"
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"RawEvent(id={self.pk}, received_at={self.received_at})"


class BackupStatus(models.TextChoices):
    """一筆備份記錄的四種狀態（FR-9）。"""

    PENDING = "PENDING", "等待處理"
    SUCCESS = "SUCCESS", "已成功備份"
    FAILED = "FAILED", "重試多次後仍失敗"
    SKIPPED = "SKIPPED", "不符合備份條件"


class SourceType(models.TextChoices):
    """訊息來自哪一種對話。"""

    USER = "user", "1 對 1"
    GROUP = "group", "群組"
    ROOM = "room", "多人聊天室"


class BackupRecord(models.Model):
    """一則 LINE 訊息 = 一筆備份記錄。"""

    raw_event = models.ForeignKey(
        RawEvent,
        on_delete=models.CASCADE,
        related_name="backup_records",
    )

    # 防重複的兩道唯一限制（FR-8）：擋重送、擋重複訊息。
    webhook_event_id = models.CharField(max_length=128, unique=True)
    line_message_id = models.CharField(max_length=128, unique=True, null=True, blank=True)

    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    source_id = models.CharField(max_length=128)
    sender_id = models.CharField(max_length=128, null=True, blank=True)

    # 決定走 Notion 還是 Google Drive；非訊息事件存事件類型本身（例如 "follow"）。
    message_type = models.CharField(max_length=32)

    status = models.CharField(
        max_length=16,
        choices=BackupStatus.choices,
        default=BackupStatus.PENDING,
    )
    attempts = models.PositiveSmallIntegerField(default=0)

    # 備份成功後的 Notion page id 或 Drive file id。
    target_ref = models.CharField(max_length=256, null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    line_timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "backup_record"
        ordering = ["id"]
        indexes = [models.Index(fields=["status"], name="backup_record_status_idx")]

    def __str__(self) -> str:
        return f"BackupRecord(id={self.pk}, type={self.message_type}, status={self.status})"
