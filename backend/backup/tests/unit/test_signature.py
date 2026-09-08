"""簽章驗證測試（FR-2、Edge case 1）。"""

from backup.utils.signature import calculate_signature, is_valid_signature

SECRET = "channel-secret"
BODY = b'{"events":[]}'


def test_correct_signature_passes():
    signature = calculate_signature(SECRET, BODY)
    assert is_valid_signature(SECRET, BODY, signature) is True


def test_wrong_signature_fails():
    assert is_valid_signature(SECRET, BODY, "definitely-not-the-signature") is False


def test_signature_of_other_body_fails():
    signature = calculate_signature(SECRET, b'{"events":[1]}')
    assert is_valid_signature(SECRET, BODY, signature) is False


def test_missing_signature_fails():
    assert is_valid_signature(SECRET, BODY, None) is False
    assert is_valid_signature(SECRET, BODY, "") is False


def test_missing_secret_fails():
    """secret 沒設定時寧可全部拒絕，也不要放行假請求。"""
    assert is_valid_signature("", BODY, calculate_signature(SECRET, BODY)) is False
