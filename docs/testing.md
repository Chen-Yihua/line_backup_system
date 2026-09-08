# Testing

## 怎麼跑

```bash
cd backend && pytest
```

設定在 `backend/pytest.ini`：測試設定用 `config.settings_test`（不需要 `.env`），
coverage 門檻 80%，低於就讓測試失敗。

所有外部服務（LINE / Notion / Google Drive）都用注入假物件的方式測，
測試過程不會連任何網路。

---

## Unit Test

| 對象 | 測試檔 |
|---|---|
| Signature | `tests/unit/test_signature.py` |
| Parser（`parse_event`） | `tests/unit/test_event_service.py` |
| Text Splitter | `tests/unit/test_text_splitter.py` |
| MIME / 檔案大小 | `tests/unit/test_mime.py` |
| Notion Client | `tests/unit/test_notion_client.py` |
| Line Client | `tests/unit/test_line_client.py` |
| Drive Client | `tests/unit/test_drive_client.py` |
| Backup Service / Router | `tests/unit/test_backup_service.py` |
| Retry Service | `tests/unit/test_retry_service.py` |
| Repository | `tests/unit/test_repository.py` |
| Model constraint | `tests/unit/test_models.py` |

## Integration Test

| 範圍 | 測試檔 |
|---|---|
| Webhook → 資料庫 | `tests/integration/test_webhook.py` |
| Webhook → Worker → Notion / Drive | `tests/integration/test_backup_flow.py` |

---

## Edge Case 對照表

對應 [PRD.md](../PRD.md) §6 的 11 個情境。

| # | 情境 | 測試 |
|---|---|---|
| 1 | 簽章缺少或錯誤 | `test_signature.py::test_wrong_signature_fails`、`test_webhook.py::test_invalid_signature_is_rejected_and_stores_nothing`、`::test_missing_signature_header_is_rejected` |
| 2 | 同一個 Webhook 被重送 | `test_webhook.py::test_duplicate_event_returns_200_without_second_record` |
| 3 | 空白文字訊息 | `test_backup_service.py::test_blank_text_is_skipped_without_calling_notion` |
| 4 | 文字超過 Notion 上限 | `test_text_splitter.py::test_long_text_is_split_without_losing_content`、`test_notion_client.py::test_long_text_becomes_multiple_blocks` |
| 5 | 檔案太大或格式不允許 | `test_mime.py::test_oversized_file_is_skipped`、`::test_disallowed_format_is_skipped`、`test_backup_service.py::test_oversized_media_is_skipped` |
| 6 | LINE 內容已過期 | `test_line_client.py::test_expired_or_missing_content_is_permanent`、`test_retry_service.py::test_permanent_error_fails_without_retry` |
| 7 | Notion API timeout / 錯誤 | `test_notion_client.py::test_server_side_errors_are_transient`、`::test_timeout_is_transient` |
| 8 | Google Drive API timeout / 錯誤 | `test_drive_client.py::test_server_side_errors_are_transient`、`::test_network_error_is_transient` |
| 9 | 不支援的訊息類型 | `test_backup_service.py::test_router_skips_unsupported_types`、`test_retry_service.py::test_unsupported_type_is_skipped` |
| 10 | 非訊息事件 | `test_event_service.py::test_non_message_event_is_recorded_without_message_id` |
| 11 | 兩個重複事件幾乎同時送達 | `test_models.py::test_duplicate_webhook_event_id_is_rejected_by_database`、`test_repository.py::test_duplicate_returns_none_instead_of_raising` |

其他重點案例：

- 空的 `events: []`（LINE 後台 Verify）→ `test_webhook.py::test_empty_events_returns_200`
- 資料庫寫入失敗要回 `500` 讓 LINE 重送 → `test_webhook.py::test_database_failure_returns_500_so_line_retries`
- 重試上限用完就停手（FR-7）→ `test_retry_service.py::test_transient_error_fails_after_max_attempts`
- 兩個 worker 不會重複領同一筆 → `test_repository.py::test_claim_moves_on_when_a_record_is_stolen`

---

## Optional Notes（之後才需要考慮，現在不用做）

- 用 GitHub Actions 在每次 push 自動跑測試。
- 對真實 API 的 contract test（目前全部用假物件）。
- 效能 / 負載測試。
