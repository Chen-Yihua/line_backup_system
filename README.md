# LINE Message Archive System

一個事件驅動的 LINE 訊息歸檔系統：文字進 Notion、媒體進 Google Drive，
每則訊息的備份狀態記在資料庫裡。

- 需求：[PRD.md](PRD.md)
- 架構：[docs/architecture.md](docs/architecture.md)
- 資料庫：[docs/database.md](docs/database.md)
- 工作清單：[TASKS.md](TASKS.md)

---

## 專案背景

這個專案源自 2022 年的工作需求：團隊日常用 LINE 群組溝通，
群組裡傳的檔案和照片過一段時間就會過期，而且散落在各個聊天室，
需要時很難找。當時主管希望在不改變大家使用習慣的前提下，把工作群組的檔案自動留存下來。

解法是把 LINE Bot 加進既有群組：群組裡傳的訊息會透過 Webhook 送到後端，
文字寫進 Notion、媒體上傳到 Google Drive，成員不需要做任何額外操作。

為什麼不用現成方案：

| 方案 | 不適用的原因 |
|---|---|
| LINE 官方聊天記錄備份 | 只能還原回 LINE，無法成為可搜尋、可管理的檔案庫 |
| 手動存到 Keep / 下載 | 要靠每個人記得做，檔案仍然分散 |
| 改用 LINE WORKS | 同事與客戶都已在一般 LINE 上，全部轉移的成本太高 |

原始版本的程式碼屬於公司，這個 repo 是我依照當時的需求**重新實作**的版本，
並補強了 Webhook 重送防重複、失敗重試與錯誤分類、自動化測試等可靠性設計。

2022 年之後 LINE Messaging API 的使用方式也有調整，重做時一併對應：

| 變化 | 本專案的對應 |
|---|---|
| 2024 年起不能直接在 LINE Developers Console 建立 Messaging API channel，要先建立 LINE 官方帳號，再到 LINE Official Account Manager 啟用 Messaging API | 依新流程更新下方「外部平台設定」 |
| 官方 Python SDK 改版為 v3（`linebot.v3`），舊版 API 已標為 deprecated | 只需要「下載訊息內容」一支 endpoint，直接用 `requests` 呼叫，不依賴 SDK，日後 SDK 再改版也不受影響 |

**限制**：受限於 LINE Messaging API，Bot 只收得到它所在的對話，
無法備份一般的一對一私人聊天，也拿不到 Bot 加入之前的舊訊息。

---

## 快速開始（本機）

本機與正式都用 PostgreSQL（見 [docs/database.md](docs/database.md) Migration Strategy），
所以本機也需要一顆能連線的 PostgreSQL。用專案根目錄的 `docker-compose.yml` 起一個
（帳密已對應 `.env.example` 的 `DATABASE_URL`，資料存在 volume，重開不會消失）：

```bash
docker compose up -d      # 啟動
docker compose down       # 停止（加 -v 會連資料一起刪掉）
```

沒有 Docker 的話，用系統套件管理員裝 PostgreSQL 也可以，只要建一個
`line_backup_system` 資料庫，帳密對應 `.env` 的 `DATABASE_URL` 即可。

```bash
# 在專案根目錄建立虛擬環境（整個專案共用這一個 .venv）
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # 填入下面「外部平台設定」拿到的值，DATABASE_URL 對應上面的 PostgreSQL
cd backend
python manage.py migrate
python manage.py runserver
```

另一個終端機開 ngrok，把對外網址填回 LINE 後台：

```bash
ngrok http 8000
```

背景 worker 手動跑一輪：

```bash
python manage.py process_pending_backups --limit 20
```

跑測試（LINE / Notion / Drive 都用假的，但需要上面那顆本機 PostgreSQL 開著——
Django 會自動建立/清掉 `test_line_backup_system`，不會動到開發用的資料）：

```bash
cd backend && pytest
```

---

## 外部平台設定

程式碼已經寫好，但下面幾件事必須在各平台的後台手動完成，
拿到的值填進 `.env`（欄位對照 [.env.example](.env.example)）。

### 1. LINE Messaging API

1. 到 [LINE Official Account Manager](https://manager.line.biz/) 建立 LINE 官方帳號，
   在 設定 → Messaging API 按「啟用 Messaging API」並選擇 Provider。
   之後這個 channel 會出現在 [LINE Developers Console](https://developers.line.biz/console/)，
   以下步驟都在 Console 裡操作。
2. Basic settings → 複製 **Channel secret** → `LINE_CHANNEL_SECRET`
3. Messaging API → 發行 **Channel access token (long-lived)** → `LINE_CHANNEL_ACCESS_TOKEN`
4. Messaging API → Webhook URL 填 `https://<ngrok 網址>/webhook`，
   打開 **Use webhook**，關掉 **Auto-reply messages**。
5. 按 **Verify**，應該要回 `200`（系統對空的 `events: []` 會正常回應）。

### 2. Notion

1. 到 [Notion Integrations](https://www.notion.so/my-integrations) 建立 internal integration，
   複製 token → `NOTION_TOKEN`
2. 建立一個 database，屬性名稱要一模一樣（大小寫也是）：

   | 屬性名稱 | 型別 |
   |---|---|
   | `Message` | Title |
   | `Sender` | Text |
   | `Source` | Text |
   | `LINE Message ID` | Text |
   | `Sent At` | Date |

3. 在該 database 頁面右上 `…` → **Connections** → 加入剛剛的 integration
   （沒做這步 API 會回 404）。
4. 複製 database ID（網址中 32 碼那段）→ `NOTION_DATABASE_ID`

### 3. Google Drive

1. Google Cloud Console → 建立專案 → 啟用 **Google Drive API**。
2. 建立 **Service Account**，產生 JSON 金鑰，存到專案外的安全位置，
   路徑填 `GOOGLE_APPLICATION_CREDENTIALS`（金鑰檔絕對不要進版控）。
3. 準備備份用的根資料夾，資料夾 ID 填 `GOOGLE_DRIVE_ROOT_FOLDER_ID`，
   並把資料夾分享給 service account 的 email，權限給 **編輯者**。

> **注意**：service account 沒有自己的 Drive 容量。如果根資料夾放在個人的「我的雲端硬碟」，
> 上傳會失敗（`storageQuotaExceeded`）。建議放在 **共用雲端硬碟 (Shared Drive)**，
> 並把 service account 加為成員。程式已經帶 `supportsAllDrives`，共用雲端硬碟可直接用。

### 4. 部署（Epic 7）

正式環境還需要：PostgreSQL 執行個體（`DATABASE_URL`）、
排程定期呼叫 `process_pending_backups`、以及把 LINE Webhook URL 換成正式網址。

---

## 設計重點

| 決定 | 為什麼 |
|---|---|
| 先存 `PENDING` 再回 `200`，備份在背景做 | LINE 要求 Webhook 快速回應，上傳影片不快 |
| 用資料庫 UNIQUE constraint 擋重複，不用 `if exists()` | 重複事件同時到達時程式判斷會有 race condition |
| 錯誤分成 Transient / Permanent / Skip | 網路斷線值得重試，內容過期重試幾次都一樣 |
| 檔案格式看 magic bytes，不看副檔名 | 副檔名與 Content-Type 都可以偽造 |
| Client 全部可注入 | 測試不打真的網路（覆蓋率 ≥ 80%） |
