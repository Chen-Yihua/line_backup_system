"""結構化 JSON log formatter。

NFR 要求 log 是 JSON、且不含訊息內容或密鑰。這裡只輸出固定欄位，
額外資訊要靠 `logger.info("...", extra={"context": {...}})` 明確傳入，
避免有人不小心把整個 payload 印出來。
"""

import json
import logging
from typing import Any


class JsonFormatter(logging.Formatter):
    """把 LogRecord 轉成單行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload["context"] = context

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)
