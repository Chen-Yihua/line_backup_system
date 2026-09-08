"""Webhook 進入點（docs/api.md）。

View 只負責 HTTP：驗簽章、解析 JSON、把事情交給 Service、決定 status code。
任何商業邏輯都不寫在這裡。
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db import DatabaseError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backup.services.event_service import EventService
from backup.utils.signature import is_valid_signature

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "HTTP_X_LINE_SIGNATURE"


@method_decorator(csrf_exempt, name="dispatch")
class LineWebhookView(APIView):
    """`POST /webhook`：驗證後立刻存檔並回 200，不等備份完成。"""

    authentication_classes: list = []
    permission_classes: list = []

    def __init__(self, event_service: EventService | None = None, **kwargs) -> None:
        """`event_service` 可注入，測試時能換成假的 Service。"""
        super().__init__(**kwargs)
        self._event_service = event_service or EventService()

    def post(self, request: Request) -> Response:
        """處理一次 Webhook 請求。"""
        body: bytes = request.body
        signature = request.META.get(SIGNATURE_HEADER)

        if not is_valid_signature(settings.LINE_CHANNEL_SECRET, body, signature):
            logger.warning("rejected webhook", extra={"context": {"reason": "invalid_signature"}})
            return _error("invalid_signature", status.HTTP_401_UNAUTHORIZED)

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("rejected webhook", extra={"context": {"reason": "invalid_payload"}})
            return _error("invalid_payload", status.HTTP_400_BAD_REQUEST)

        if not isinstance(payload, dict):
            return _error("invalid_payload", status.HTTP_400_BAD_REQUEST)

        try:
            self._event_service.ingest(payload)
        except DatabaseError:
            # 回 500 讓 LINE 重送，不能回 200 假裝收到了（docs/workflow.md「Webhook」）。
            logger.exception("failed to persist webhook")
            return _error("internal_error", status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"status": "ok"}, status=status.HTTP_200_OK)


def _error(code: str, http_status: int) -> Response:
    """docs/api.md 定義的錯誤格式。"""
    return Response({"error": code}, status=http_status)
