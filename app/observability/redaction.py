from typing import Any

# 第 17 节：日志绝不能包含的敏感字段（键名小写匹配）。
_SENSITIVE_KEYS = frozenset(
    {
        "cookie",
        "cookies",
        "set-cookie",
        "authorization",
        "auth",
        "proxy_password",
        "proxy_auth",
        "password",
        "api_key",
        "apikey",
        "token",
        "account",
        "session_id",
        # Phase 3b 登录/加密敏感字段（设计 §8.2）。
        "profile_encryption_key",
        "encryption_key",
        "qr_png",
        "qr_png_base64",
    }
)

# 页面正文类字段只保留头部，避免把完整正文写进日志。
_TRUNCATE_KEYS = frozenset({"body", "html", "html_content", "markdown", "text"})
_TRUNCATE_LIMIT = 200
_MASK = "***"
_TRUNCATE_SUFFIX = "...[truncated]"


def redact(value: Any) -> Any:
    """返回脱敏后的深拷贝，不修改入参（不可变风格）。

    敏感键值替换为掩码；正文类字段截断到前若干字符。
    """
    if isinstance(value, dict):
        return {key: _redact_pair(key, val) for key, val in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _redact_pair(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered in _SENSITIVE_KEYS:
        return _MASK
    if lowered in _TRUNCATE_KEYS and isinstance(value, str) and len(value) > _TRUNCATE_LIMIT:
        return value[:_TRUNCATE_LIMIT] + _TRUNCATE_SUFFIX
    return redact(value)
