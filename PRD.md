# LINE Backup System — PRD (MVP)

| | |
|---|---|
| Version | 3.0 |
| Date | 2026-07-29 |
| Scope | Side project — 目標是把設計講清楚、做出來，不是企業內部規格書 |

---

## 1. Project Goal

### 這是什麼

一個 LINE Bot，自動把對話裡的訊息備份起來：

- 文字 → Notion
- 圖片 / 影片 / 檔案 / 語音 → Google Drive
- 每一則訊息的備份狀態 → 記錄在資料庫裡

### 為什麼要做

LINE 裡的訊息（照片、檔案、筆記）容易遺失、不好搜尋。這個專案用來練習、也用來展示後端工程的基本功：分層架構、防止重複處理、寫測試。範圍刻意做小，確保每個決定都能講清楚為什麼，而不是求功能多。

### 完成的定義 (Success Criteria)

| 項目 | 標準 |
|---|---|
| 正確性 | 每則支援的訊息都會備份到 Notion 或 Drive，且只會存一次 |
| 防重複 | 就算 LINE 重送同一個 Webhook，也不會備份兩次 |
| 回應速度 | Webhook 立刻回應，備份工作在背景進行 |
| 測試 | 覆蓋率 ≥ 80%，外部 API（LINE / Notion / Drive）在測試中全部用假的 |
| 可解釋 | 整個設計可以在 10 分鐘內講完 |

---

## 2. User Story

身份：**Owner**（安裝這個 Bot、擁有 Notion 資料庫和 Drive 資料夾的人）

| 我想要 | 所以 | 怎麼確認做到了 |
|---|---|---|
| 每則訊息自動備份 | 不會遺失重要資訊 | 傳一則訊息，去 Notion / Drive 檢查有沒有出現 |
| 文字進 Notion | 方便搜尋、整理 | 一則文字 = Notion 裡一筆資料 |
| 圖片 / 影片 / 檔案 / 語音進 Drive | 方便檢視、分享 | 一個檔案 = Drive 裡一個檔案 |
| 知道備份成功或失敗 | 才能信任這個系統 | 資料庫裡每筆記錄都有明確狀態（見 [database.md](docs/database.md)） |

---

## 3. Use Case

| UC | 情境 | 流程 |
|---|---|---|
| UC-1 文字備份 | 使用者傳文字訊息 | Webhook → 驗證簽章 → 存 `PENDING` → 回 `200` → 寫入 Notion → 標記 `SUCCESS` |
| UC-2 媒體備份 | 使用者傳圖片 / 影片 / 檔案 / 語音 | Webhook → 驗證簽章 → 存 `PENDING` → 回 `200` → 下載內容 → 上傳 Drive → 標記 `SUCCESS` |
| UC-3 重複 Webhook | LINE 重送同一個事件（很常見） | 靠 `webhook_event_id` 的唯一限制擋掉，回 `200` 但不會重複備份 |
| UC-4 未驗證請求 | 簽章錯誤或缺少 | 回 `401` / `400`，不存任何資料 |

這 4 個 Use Case 對應 4 個最值得講清楚的設計：非同步回應、媒體處理、防重複、安全性。細節見 [architecture.md](docs/architecture.md)。

---

## 4. Functional Requirements

| ID | 需求 |
|---|---|
| FR-1 | 接收 LINE Webhook：`POST /webhook`。 |
| FR-2 | 驗證 `X-Line-Signature`（HMAC-SHA256），失敗回 `401` / `400`。 |
| FR-3 | 先存資料、立刻回 `200`；實際備份工作在之後（背景）完成，不在同一個請求裡做。 |
| FR-4 | 支援訊息類型：文字、圖片、影片、檔案、語音。其他類型記錄為 `unsupported`，不會被靜默丟掉。 |
| FR-5 | 文字訊息備份進 Notion 資料庫（一筆訊息 = 一列，含文字、寄件人、來源、時間、LINE 訊息 ID）。 |
| FR-6 | 媒體訊息上傳到 Google Drive，依對話分資料夾；Drive 檔案 ID 存進資料庫。 |
| FR-7 | 失敗時（timeout、5xx、網路問題）固定重試 3 次，之後標記 `FAILED`，不會無限重試。 |
| FR-8 | 用資料庫的唯一限制防止重複備份：`webhook_event_id`（擋重複送信）+ `line_message_id`（擋重複訊息）。 |
| FR-9 | 每筆記錄都有狀態：`PENDING` / `SUCCESS` / `FAILED` / `SKIPPED`。 |
| FR-10 | 所有密鑰（LINE token/secret、Notion token、Google 憑證）從環境變數讀取，不寫死在程式裡。 |

---

## 5. Non-Functional Requirements

| 項目 | 要求 |
|---|---|
| 回應速度 | Webhook 要馬上回應，不等 Notion / Drive 處理完才回 |
| 可靠性 | 一筆記錄要嘛完成、要嘛清楚標記失敗，不會卡在不明狀態 |
| 安全性 | 一定要驗證簽章、只用 HTTPS、Log 不能記錄訊息內容或密鑰 |
| 可測試性 | 測試覆蓋率 ≥ 80%，外部 API 都用假的物件測試，不打真的網路 |
| 可維護性 | 分層架構（View 不寫邏輯、Model 不寫邏輯），新增功能不用改舊程式 |
| Log | 結構化 JSON log，內容不含個資或密鑰 |

---

## 6. Edge Cases

| # | 情境 | 預期行為 |
|---|---|---|
| 1 | 簽章缺少或錯誤 | 拒絕，不存任何資料 |
| 2 | 同一個 Webhook 被重送 | 只備份一次，仍回 `200` |
| 3 | 空白文字訊息 | 跳過，不建立空的 Notion 資料列 |
| 4 | 文字超過 Notion 單一區塊字數上限 | 自動分段，不遺漏內容 |
| 5 | 檔案太大或格式不允許 | 標記 `SKIPPED`，不上傳 |
| 6 | LINE 的內容已過期抓不到 | 標記 `FAILED`，不會一直重試 |
| 7 | Notion API timeout / 錯誤 | 依 FR-7 重試，仍失敗則 `FAILED` |
| 8 | Google Drive API timeout / 錯誤 | 同上 |
| 9 | 不支援的訊息類型（貼圖、位置、聯絡人） | 標記 `unsupported`，不會讓程式壞掉 |
| 10 | 非訊息事件（加入/離開群組、追蹤/取消追蹤） | 記錄下來，但不嘗試備份 |
| 11 | 兩個重複事件幾乎同時送達 | 靠資料庫唯一限制決定只有一筆成功，不是程式邏輯判斷 |

---

## 7. Future Features

刻意先不做，讓 v1 範圍維持精簡：

- Exponential backoff + dead-letter queue + 告警（v1 只做固定次數重試）。
- 內容去重（同一個檔案傳兩次目前會備份兩次）。
- 圖片 OCR / 語音轉文字，存進 Notion。
- 網頁版備份狀態儀表板。
- 支援其他聊天平台（Slack、Discord）。
- 多租戶（多組 LINE 帳號 / Notion / Drive，各自獨立）。
- 使用者收回訊息（Unsend）的處理（刪除或標記對應備份）。

---

## 8. Out of Scope

- 備份 Bot 加入對話**之前**的舊訊息（LINE API 本身就不提供歷史訊息，技術上做不到）。
- LINE 以外的平台。
- 使用者介面（Web / App）——Notion 和 Drive 本身就是介面。
- 雙向同步（在 Notion / Drive 編輯不會同步回 LINE）。
- 正式的高可用性 / 大流量設計——這是單一使用者的 side project。
- AI 相關功能（摘要、翻譯、OCR）。

---

## 9. Key Design Decisions

| 決策 | 為什麼 |
|---|---|
| 先存資料庫再回 `200`，備份工作在背景做 | LINE 要求 Webhook 要快，上傳檔案不快，兩者放一起會逾時。 |
| 用資料庫 unique constraint 擋重複，不是程式判斷 `if exists()` | 兩個重複事件同時進來時，程式判斷會有 race condition，資料庫限制不會。 |
| 分層架構（View / Service / Repository / Client） | 方便加新功能、方便寫測試（可以塞假的 Client 進去）。 |
| 固定重試 3 次，沒有 dead-letter queue | 現在的規模不需要更複雜的重試機制，之後真的需要再加（見 Optional Notes）。 |
| 一個 Notion 資料庫、一個 Drive 資料夾 | 目前只有一個使用者，不需要多租戶設計。 |
| Drive 用 OAuth（使用者本人授權）上傳，不用 Service Account | Service Account 沒有自己的 Drive 容量，只能寫進共用雲端硬碟，但共用雲端硬碟要付費的 Workspace 才有。用 OAuth 以本人身分上傳，個人 Gmail 帳號也能存進自己的 Drive。 |

---

## Optional Notes（之後才需要考慮，現在不用做）

- 正式的 SLA / 可用性目標（例如 99% 之類的數字）。
- 大流量負載測試、水平擴展。
- Dead-letter queue + 告警系統。
- 多租戶（多組 LINE / Notion / Drive 帳號）。
- 內容去重、正式的隱私/資料保留政策。
