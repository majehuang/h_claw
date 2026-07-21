from app.observability.redaction import redact


def test_redacts_top_level_sensitive_keys():
    data = {
        "url": "https://shop.example.com/p/1",
        "cookie": "session=abc123",
        "authorization": "Bearer secrettoken",
        "proxy_password": "hunter2",
    }
    result = redact(data)

    assert result["url"] == "https://shop.example.com/p/1"
    assert result["cookie"] == "***"
    assert result["authorization"] == "***"
    assert result["proxy_password"] == "***"


def test_redacts_phase3_login_secrets():
    # Phase 3b（设计 §8.2）：登录密钥、二维码、cookie 绝不进日志。
    data = {
        "profile_encryption_key": "s3cr3t-master-key",
        "encryption_key": "another",
        "qr_png_base64": "iVBORw0KGgoAAAANSUhEUg==",
        "session_id": "jd-user-001",
        "domain": "www.jd.com",
    }
    result = redact(data)

    assert result["profile_encryption_key"] == "***"
    assert result["encryption_key"] == "***"
    assert result["qr_png_base64"] == "***"
    assert result["session_id"] == "***"
    assert result["domain"] == "www.jd.com"  # 非敏感字段保留


def test_key_matching_is_case_insensitive():
    data = {"Cookie": "x", "AUTHORIZATION": "y", "Set-Cookie": "z"}
    result = redact(data)
    assert result["Cookie"] == "***"
    assert result["AUTHORIZATION"] == "***"
    assert result["Set-Cookie"] == "***"


def test_redacts_nested_dicts():
    data = {
        "request": {
            "headers": {"authorization": "Bearer t", "user-agent": "curl"},
        }
    }
    result = redact(data)
    assert result["request"]["headers"]["authorization"] == "***"
    assert result["request"]["headers"]["user-agent"] == "curl"


def test_redacts_inside_lists():
    data = {"items": [{"cookie": "a"}, {"safe": "b"}]}
    result = redact(data)
    assert result["items"][0]["cookie"] == "***"
    assert result["items"][1]["safe"] == "b"


def test_truncates_page_body_field():
    data = {"body": "x" * 5000}
    result = redact(data)
    assert result["body"].endswith("...[truncated]")
    assert len(result["body"]) < 5000


def test_redacts_account_and_password_fields():
    data = {"account": "user@example.com", "password": "p", "api_key": "k"}
    result = redact(data)
    assert result["account"] == "***"
    assert result["password"] == "***"
    assert result["api_key"] == "***"


def test_does_not_mutate_input():
    data = {"cookie": "secret"}
    redact(data)
    assert data["cookie"] == "secret"  # 原对象不被修改（不可变风格）
