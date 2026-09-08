"""長文字切割測試（Edge case 3、4）。"""

import pytest

from backup.utils.text_splitter import NOTION_TEXT_LIMIT, make_title, split_text


def test_normal_text_stays_in_one_chunk():
    assert split_text("hello world") == ["hello world"]


def test_long_text_is_split_without_losing_content():
    text = "a" * (NOTION_TEXT_LIMIT * 2 + 5)
    chunks = split_text(text)

    assert len(chunks) == 3
    assert all(len(chunk) <= NOTION_TEXT_LIMIT for chunk in chunks)
    assert "".join(chunks) == text


def test_text_exactly_at_limit_is_one_chunk():
    assert len(split_text("a" * NOTION_TEXT_LIMIT)) == 1


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_blank_text_returns_nothing(text):
    assert split_text(text) == []


def test_invalid_limit_raises():
    with pytest.raises(ValueError):
        split_text("hello", limit=0)


def test_make_title_truncates_long_text():
    title = make_title("a" * 500, limit=10)
    assert len(title) == 10
    assert title.endswith("…")


def test_make_title_condenses_whitespace():
    assert make_title("hello\n\n  world") == "hello world"
