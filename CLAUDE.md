# LINE Message Archive System

## Goal

一個事件驅動的 LINE 訊息歸檔系統 side project。

系統透過 LINE Messaging API Webhook 接收訊息事件，
將不同類型的訊息轉換成可管理的資料：

- 文字訊息保存至資料庫，並同步至 Notion。
- 圖片、影片、檔案、語音等媒體檔案保存至 Google Drive。
- 記錄每個事件的處理狀態。
- 透過 event id 與資料庫 constraint 避免 webhook retry 造成重複處理。
- 設計可維護、可測試、可擴充的後端架構。


本專案的目的不是取代 LINE 官方備份功能，
而是練習建立一個外部事件整合系統：

- Webhook event handling
- External API integration
- Data persistence
- Error handling
- Idempotent processing
- Testing


本專案刻意維持 MVP 範圍，
優先確保架構清楚、每個設計決策可以被解釋，
而不是追求大型分散式系統。


完整需求：
- PRD.md

架構設計：
- docs/architecture.md

資料庫設計：
- docs/database.md


---

# Tech Stack

## Language

Python 3.12


## Backend Framework

Django
Django REST Framework


## External Services

LINE Messaging API

Notion API

Google Drive API


## Database

Development:
- PostgreSQL

Production:
- PostgreSQL


## Background Processing

MVP:
- Django Background Task / Celery (optional)

Future:
- Message Queue


## Deployment

Docker

Google Cloud Run


## Testing

pytest

Django Test Framework


## Development Tools

ngrok
Git
GitHub Actions


---

# Development Rules

## Before Writing Code

一定要：

1. 先閱讀：

- PRD.md
- docs/architecture.md
- docs/database.md


2. 先確認：

- 這個功能是否屬於 MVP 範圍。
- 是否需要修改 architecture.md。
- 是否會影響 database schema。


3. 開始 coding 前：

先提出：

- 實作方案
- 影響範圍
- 可能風險


確認後再開始實作。


---

# Implementation Rules

## 必須遵守

- 一次只實作一個 module。
- 遵循目前 architecture design。
- 保持 service layer 與 external API client 分離。
- 所有外部 API 呼叫必須可測試。
- 所有重要功能需要加入測試。
- 修改架構時同步更新文件。


---

# 不要做

禁止：

- 一次生成完整專案。
- 把 API key、token 寫死在程式。
- 直接修改 database schema 而沒有 migration。
- 跳過測試。
- 為了展示技術加入沒有需求的功能。


不要在 MVP 階段加入：

- Kubernetes
- Microservices
- Kafka
- 多租戶架構
- Dead Letter Queue
- 複雜權限系統
- 分散式 transaction


除非：

PRD 或 architecture 文件先更新，
並且說明加入原因。


---

# Engineering Principles

## Simplicity First

優先選擇：

簡單、容易測試、容易維護的設計。


## Explainability

每個技術選擇都需要回答：

- 為什麼需要？
- 解決什麼問題？
- 有沒有更簡單方案？


## Reliability

處理外部事件時必須考慮：

- webhook retry
- duplicate event
- API failure
- partial failure


## Maintainability

程式碼應該：

- 模組化
- 低耦合
- 容易替換 external service