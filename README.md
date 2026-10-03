# LINE Message Archive System

一個事件驅動的 LINE 訊息歸檔系統：文字進 Notion、媒體進 Google Drive，
每則訊息的備份狀態記在資料庫裡。

- 需求：[PRD.md](PRD.md)
- 架構：[docs/architecture.md](docs/architecture.md)
- 資料庫：[docs/database.md](docs/database.md)
- 工作清單：[TASKS.md](TASKS.md)

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

1. 到 [LINE Developers Console](https://developers.line.biz/console/) 建立 Provider 與
   **Messaging API** channel。
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
