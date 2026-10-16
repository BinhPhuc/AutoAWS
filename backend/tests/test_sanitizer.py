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
