from app.sanitizer import sanitize, sanitize_text


def test_masks_access_keys_and_secrets():
    text = "key AKIAIOSFODNN7EXAMPLE secret_key=abc123 password: hunter2 Bearer eyJhbGci"
    out = sanitize_text(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out and "[AWS_ACCESS_KEY]" in out
    assert "abc123" not in out
    assert "hunter2" not in out
    assert "eyJhbGci" not in out


def test_masks_emails_but_keeps_resource_ids():
    out = sanitize({"user": "dev.tuan@example.com", "sg": "sg-0d4e1234", "ip": "54.169.1.2"})
    assert out["user"] == "[EMAIL]"
    assert out["sg"] == "sg-0d4e1234"
    assert out["ip"] == "54.169.1.2"


def test_redacts_secret_keys_and_truncates_lists():
    out = sanitize({"SecretAccessKey": "x", "items": list(range(30))}, max_list_items=25)
    assert out["SecretAccessKey"] == "[REDACTED]"
    assert len(out["items"]) == 26
    assert out["items"][-1] == {"_truncated": 5}


def test_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
    assert sanitize_text(f"cfg {pem} end") == "cfg [PRIVATE_KEY] end"


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "phone",
    [
        "0912345678",
        "0912 345 678",
        "091-234-5678",
        "024 3826 1234",
        "+84 912 345 678",
        "+84912345678",
        "+1 415 555 0100",
    ],
)
def test_masks_phone_numbers(phone):
    assert sanitize_text(f"order from {phone} failed") == "order from [PHONE] failed"


@pytest.mark.parametrize(
    "keep",
    [
        "012345678901",  # 12-digit account id
        "arn:aws:iam::012345678901:role/R",
        "i-0123456789abcdef0",
        "10.0.1.25",
        "0.0.0.0/0",
        "1024-65535",
        "2026-10-09T09:14:00Z",
        "subnet-0123456789",
        "counts 0 0 0 0 0 0 0 0 0 0",
    ],
)
def test_phone_masking_keeps_diagnosis_data(keep):
    assert sanitize_text(keep) == keep
