# Tasks

把 [PRD.md](PRD.md) 的 10 個 Functional Requirement 拆成可以實際動手做的工作清單，順序大致對應 CLAUDE.md「一次只做一個 module」的原則。

結構：**Epic → Feature → Task → Subtask**

| 層級 | 意思 |
|---|---|
| Epic | 一個大方向（例如「Webhook 接收」） |
| Feature | Epic 底下具體的功能 |
| Task | **不超過 1 天**能做完的工作 |
| Subtask | Task 裡可以打勾的小步驟 |

---

## Epic 1：專案基礎建設

### Feature 1.1：Django 專案初始化

- [x] **Task**：建立專案骨架（對應 [architecture.md](docs/architecture.md) Folder Structure）
  - [x] `django-admin startproject config .`
  - [x] `python manage.py startapp backup`
  - [x] 建立 `services/`、`clients/`、`utils/`、`tests/unit`、`tests/integration` 資料夾
  - [x] 設定 `.gitignore`（排除 `.env`、`__pycache__`）
- [x] **Task**：環境變數設定
  - [x] 安裝 `django-environ`
  - [x] 建立 `.env.example`
  - [x] `settings.py` 改成讀環境變數，缺必要變數要在啟動時報錯（FR-10）
- [x] **Task**：安裝依賴與程式碼風格工具
  - [x] 建立 `requirements.txt`
  - [x] 安裝 Django、DRF、pytest、pytest-django、black、isort
  - [x] 設定 Black / isort 設定檔（`pyproject.toml`）

### Feature 1.2：本機開發環境

- [x] **Task**：確認本機可以跑起來
  - [x] `python manage.py runserver` 正常啟動（本機 PostgreSQL，`docker compose up -d`）
  - [x] 設定 ngrok，取得對外網址
- [x] **Task**：LINE 後台設定 ⚠️ 需要到外部平台操作，見 [README](README.md#1-line-messaging-api)
  - [x] 建立 LINE Messaging API Channel（官方帳號 → 啟用 Messaging API）
  - [x] Webhook URL 設定成 ngrok 網址
  - [x] 取得 Channel Secret / Access Token，填進 `.env`

---

## Epic 2：Webhook 接收（對應 FR-1, FR-2, FR-3, FR-8, FR-9, FR-10）

### Feature 2.1：資料模型（對應 [database.md](docs/database.md)）

- [x] **Task**：建立 `RawEvent` model
  - [x] 欄位：`payload`、`received_at`
  - [x] 寫 migration
- [x] **Task**：建立 `BackupRecord` model
  - [x] 欄位與 `status` 四種狀態（`PENDING`/`SUCCESS`/`FAILED`/`SKIPPED`）
  - [x] `webhook_event_id`、`line_message_id` 加唯一限制
  - [x] 寫 migration
  - [x] 寫測試：確認唯一限制真的擋得住重複資料

### Feature 2.2：簽章驗證

- [x] **Task**：實作 `utils/signature.py`
  - [x] HMAC-SHA256 + base64 驗證函式
  - [x] 用 `hmac.compare_digest` 做常數時間比對
  - [x] 單元測試：正確簽章 / 錯誤簽章各一個 case

### Feature 2.3：Webhook View 與 EventService（對應 [api.md](docs/api.md)）

- [x] **Task**：實作 `views.py` 的 Webhook View
  - [x] 讀取 raw body 與 `X-Line-Signature`
  - [x] 簽章不合法 → 回 401/400
  - [x] 呼叫 `EventService`，成功回 200
- [x] **Task**：實作 `EventService`
  - [x] 存 `RawEvent`
  - [x] 逐一解析 `events[]`，建立 `BackupRecord`（`PENDING`）
  - [x] 重複事件時不拋錯給使用者，正常回 200（Workflow「Duplicate」）
- [x] **Task**：實作 `repository.py` 對應的存取方法
  - [x] `create_raw_event()`
  - [x] `create_pending_backup_record()`（吃下唯一限制的例外）

### Feature 2.4：Webhook 整合測試

- [x] **Task**：寫 Webhook 整合測試
  - [x] 合法簽章 → 200，資料庫有記錄
  - [x] 錯誤簽章 → 401
  - [x] 重複事件 → 200，但沒有第二筆記錄
  - [x] 空的 `events: []`（LINE 後台驗證用）→ 200

---

## Epic 3：文字備份 → Notion（對應 FR-5）

### Feature 3.1：NotionClient

- [x] **Task**：建立 `clients/notion_client.py`
  - [x] 安裝 Notion SDK，設定 Token（Token 與 database 屬性需先在 Notion 後台建立，
    見 [README](README.md#2-notion) ⚠️）
  - [x] 實作 `append_text(database_id, text, meta) -> page_id`
  - [x] 把 Notion SDK 的例外轉成 `TransientError` / `PermanentError`
- [x] **Task**：處理長文字分段（Edge case 4）
  - [x] 實作 `utils/text_splitter.py`
  - [x] 單元測試：超長文字 / 正常文字 / 空白文字

### Feature 3.2：TextBackupService

- [x] **Task**：實作 `TextBackupService`
  - [x] 呼叫 `NotionClient` 寫入
  - [x] 空白文字 → `SKIPPED`（Edge case 3）
  - [x] 更新 `BackupRecord` 的 `target_ref` / `status`
  - [x] 單元測試（用假的 `NotionClient`）

---

## Epic 4：媒體備份 → Google Drive（對應 FR-6）

### Feature 4.1：下載 LINE 內容

- [x] **Task**：實作 `clients/line_client.py` 的 `download_content()`
  - [x] 呼叫 LINE Content API
  - [x] 內容過期/找不到 → `PermanentError`（Edge case 6）
  - [x] 單元測試（假的 HTTP response）

### Feature 4.2：檔案驗證

- [x] **Task**：實作 `utils/mime.py`
  - [x] 用內容判斷檔案格式（不信任副檔名）
  - [x] 檔案大小檢查
  - [x] 單元測試：過大檔案 / 不允許格式（Edge case 5）

### Feature 4.3：DriveClient

- [x] **Task**：建立 `clients/drive_client.py`
  - [x] ~~設定 Google Service Account 憑證~~ → 改用 OAuth（個人 Gmail 沒有共用雲端硬碟），
    見 [architecture.md](docs/architecture.md)「Google Drive 的認證方式」
  - [x] `authorize_drive` 指令：一次性授權 + 建立根資料夾
  - [ ] 實際授權並上傳一個檔案（OAuth 用戶端需先在 Google Cloud 建立，
    見 [README](README.md#3-google-drive) ⚠️）
  - [x] 找/建資料夾（依對話、年、月）
  - [x] 實作 `upload(folder, filename, bytes) -> file_id`
  - [x] 例外轉成 `TransientError` / `PermanentError`

### Feature 4.4：MediaBackupService

- [x] **Task**：實作 `MediaBackupService`
  - [x] 串起下載 → 驗證 → 上傳（Workflow「Upload」）
  - [x] 更新 `BackupRecord` 的 `target_ref` / `status`
  - [x] 單元測試：成功 / `SKIPPED` / 失敗，各一個 case

---

## Epic 5：背景處理與重試（對應 FR-7, FR-9）

### Feature 5.1：BackupRouter

- [x] **Task**：實作 `services/backup_service.py` 的 `BackupRouter`
  - [x] 訊息類型 → Service 對應表
  - [x] 未知類型 → `SKIPPED`（unsupported）
  - [x] 單元測試：每種類型都走對 Service

### Feature 5.2：RetryService 與 Worker 指令

- [x] **Task**：實作 `repository.claim_next_pending()`
  - [x] 用 transaction 確保兩個 worker 不會搶同一筆
  - [x] 單元測試：模擬同時呼叫
- [x] **Task**：實作 `RetryService.run_once()`
  - [x] 呼叫 Router → Service
  - [x] 暫時性錯誤 → `attempts += 1`，判斷要不要回 `PENDING`（Workflow「Retry」）
  - [x] 永久性錯誤 → 直接 `FAILED` / `SKIPPED`
- [x] **Task**：實作 `management/commands/process_pending_backups.py`
  - [x] 呼叫 `RetryService` 跑一輪
  - [x] 確認能處理 `PENDING` 記錄（整合測試 `test_management_command_reports_progress`；
    接真實服務的手動驗證留在 Epic 7）

---

## Epic 6：測試與品質（對應 PRD NFR「測試覆蓋率 ≥ 80%」）

- [x] **Task**：設定測試工具
  - [x] `pytest` + `pytest-django` + `coverage` 設定檔
  - [x] 設定 coverage 門檻 80%
- [x] **Task**：補齊 Edge Case 測試
  - [x] 對照 [PRD.md](PRD.md) §6 的 11 個情境，逐一確認有對應測試
- [x] **Task**：程式碼風格檢查
  - [x] 跑一次 Black / isort，確認全專案格式一致
  - [x] 檢查有沒有超過 40 行的函式、超過 300 行的檔案

---

## Epic 7：部署

⚠️ 整個 Epic 都需要在外部平台操作，等 Epic 1.2 的外部設定完成、本機跑通之後再進行。

- [ ] **Task**：準備正式環境資料庫
  - [ ] 建立 PostgreSQL 執行個體
  - [ ] 設定 `DATABASE_URL`
- [ ] **Task**：設定 Google App Engine
  - [ ] 寫 `app.yaml`
  - [ ] 設定排程觸發 `process_pending_backups`（見 [architecture.md](docs/architecture.md) Flow 2）
- [ ] **Task**：Google OAuth 改成正式版（測試狀態 token 7 天失效）
  - [ ] 準備公開的首頁與隱私權政策網址（例如 GitHub Pages），填進 Branding
  - [ ] Publish app → In production，重跑 `authorize_drive`
- [ ] **Task**：上線前檢查
  - [ ] 部署前先跑 `migrate`
  - [ ] 正式環境的 LINE Webhook URL 設定完成
  - [ ] 手動傳一則文字 + 一張圖片，確認整條流程（Webhook → Notion / Drive → 狀態更新）都正確

---

## Optional Notes（之後才需要考慮，現在不用做）

- CI/CD（例如 GitHub Actions 自動跑測試、自動部署）。
- Docker 化開發環境。
- 監控 / 告警設定（對應各文件的 Optional Notes）。
