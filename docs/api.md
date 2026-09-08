# API

整個系統目前只有一支對外的 REST API：接收 LINE Webhook。

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/webhook` | 接收 LINE Messaging API 送來的事件 |

PRD 的範圍裡沒有查詢介面（見 [PRD.md](../PRD.md) Out of Scope）——Notion 和 Google Drive 本身就是使用者看備份結果的地方。之後如果要加「查詢備份狀態」的功能，再另外補規格，不用先做一整套 CRUD API。

---

## POST /webhook

### Authentication

用 `X-Line-Signature` 這個 Header 驗證請求真的是 LINE 送來的，不是任何人都能呼叫。防止有人假冒 LINE、塞假資料進資料庫。細節對應 [security.md](security.md)「Verify Signature」。

**驗證方式**

1. 用環境變數 `LINE_CHANNEL_SECRET`，對 request body 做 HMAC-SHA256。
2. 結果轉成 base64。
3. 跟 `X-Line-Signature` 的值比對（用常數時間比對，避免 timing attack）。
4. 不一致 → 回 `401`，不存任何資料。

---

### Request

LINE 送來的 JSON payload，一次請求可能包含多個事件。

Header 必填：`X-Line-Signature`

```json
{
  "destination": "Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "events": [
    {
      "type": "message",
      "webhookEventId": "01234567-89ab-cdef-0123-456789abcdef",
      "timestamp": 1462629479859,
      "source": {
        "type": "user",
        "userId": "U4af4980629..."
      },
      "deliveryContext": {
        "isRedelivery": false
      },
      "message": {
        "id": "444573844083193",
        "type": "text",
        "text": "Hello, world"
      }
    }
  ]
}
```

**關鍵欄位**（會直接存進 [database.md](database.md) 的 `BackupRecord`）

| 欄位 | 存進哪個資料庫欄位 |
|---|---|
| `events[].webhookEventId` | `webhook_event_id`（防重複送信） |
| `events[].message.id` | `line_message_id`（防重複訊息） |
| `events[].source.type` | `source_type` |
| `events[].source.userId` / `groupId` / `roomId` | `source_id` |
| `events[].message.type` | `message_type` |
| `events[].timestamp` | `line_timestamp` |

---

### Response

成功一律回：

```json
{ "status": "ok" }
```

此回應代表「有收到、有存進資料庫」，不代表「已經備份成功」。備份是不是成功，要看資料庫裡 `BackupRecord.status`（見 [database.md](database.md)）——v1 沒有對外查詢這個狀態的 API。回應要快（見 [architecture.md](architecture.md) Flow 1），所以不會等 Notion / Drive 處理完才回。

---

### Status Code

| Code | 意思 | 什麼時候發生 |
|---|---|---|
| `200` | 已接收 | 簽章正確，事件已存進資料庫 |
| `400` | 格式錯誤 | Body 不是合法 JSON，解析失敗 |
| `401` | 未授權 | 簽章缺少或不正確 |
| `500` | 伺服器錯誤 | 資料庫暫時無法寫入（LINE 會自動重送這個事件） |

---

### Error Code

`400` / `401` / `500` 會回一個簡單的錯誤格式：

```json
{ "error": "invalid_signature" }
```

| HTTP Status | error code | 意思 |
|---|---|---|
| 400 | `invalid_payload` | Body 無法解析成 JSON |
| 401 | `invalid_signature` | 缺少或驗證失敗的 `X-Line-Signature` |
| 500 | `internal_error` | 伺服器端錯誤（例如資料庫連線失敗） |

**注意**：備份本身失敗的原因（Notion timeout、檔案太大等）不會出現在這裡——那些屬於背景處理的結果，記錄在 `BackupRecord.note` 欄位（見 [database.md](database.md)），不是這支 API 的回應內容。

---

### Rate Limit

v1 沒有實作 Rate Limit。因這是單一使用者的 side project，請求是 LINE 主動推送過來的，流量本來就不大，不需要額外限制。

呼叫 Notion / Google Drive 那邊（outbound）的流量控制，是靠 FR-7 的固定重試機制處理失敗，不是用 rate limiter，詳見 [architecture.md](architecture.md)。

---

## Optional Notes（之後才需要考慮，現在不用做）

- `GET /healthz` 健康檢查端點，給監控工具用。
- 查詢備份狀態的 `GET` API（列表、依狀態篩選）。
- 針對 `/webhook` 加上 LINE 官方 IP allowlist。
- 正式的 Rate Limiting middleware（例如 `django-ratelimit`），防止惡意大量請求。
- API 版本化（例如 `/v1/webhook`）。
