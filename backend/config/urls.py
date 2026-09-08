"""URL 設定。

對外只有一支 API：`POST /webhook`（見 docs/api.md）。
"""

from django.urls import path

from backup.views import LineWebhookView

urlpatterns = [
    path("webhook", LineWebhookView.as_view(), name="line-webhook"),
]
