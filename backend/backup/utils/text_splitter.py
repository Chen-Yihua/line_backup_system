"""切割長文字（Edge case 4）。

Notion 的一個 rich text 物件最多 2000 個字元，超過就整個請求被拒絕。
所以寫入前先切成多段，寧可多幾個段落，也不要遺漏內容。
"""

# Notion API 對單一 rich text 內容的字元上限。
NOTION_TEXT_LIMIT = 2000


def split_text(text: str, limit: int = NOTION_TEXT_LIMIT) -> list[str]:
    """把文字切成不超過 `limit` 字元的段落。

    空白字串（含只有空白字元）回傳空陣列，讓呼叫端可以直接判斷「沒東西可寫」。
    """
    if limit <= 0:
        raise ValueError("limit 必須大於 0")

    if not text or not text.strip():
        return []

    return [text[index : index + limit] for index in range(0, len(text), limit)]


def make_title(text: str, limit: int = 100) -> str:
    """取一段短標題，方便在 Notion 列表頁一眼看出這筆是什麼訊息。"""
    condensed = " ".join(text.split())
    if len(condensed) <= limit:
        return condensed
    return condensed[: limit - 1] + "…"
