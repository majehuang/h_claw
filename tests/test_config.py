from pathlib import Path

from app.config import Settings


def test_defaults_match_design_doc(monkeypatch):
    for key in [
        "MCP_TRANSPORT", "MCP_HOST", "MCP_PORT", "DATA_DIR",
        "MAX_CONCURRENCY", "MAX_BROWSER_PAGES", "MAX_PER_DOMAIN",
        "HTTP_TIMEOUT_SECONDS", "BROWSER_TIMEOUT_SECONDS", "STEALTH_TIMEOUT_SECONDS",
        "CACHE_TTL_SECONDS", "RESULT_TTL_SECONDS",
        "MAX_INLINE_MARKDOWN_BYTES", "MAX_MARKDOWN_BYTES", "MAX_HTML_BYTES",
        "DATABASE_URL",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.mcp_transport == "stdio"
    assert settings.mcp_host == "0.0.0.0"
    assert settings.mcp_port == 8000
    assert settings.data_dir == Path("/data")
    assert settings.max_concurrency == 5
    assert settings.max_browser_pages == 3
    assert settings.max_per_domain == 1
    assert settings.http_timeout_seconds == 15
    assert settings.browser_timeout_seconds == 60
    assert settings.stealth_timeout_seconds == 90
    assert settings.cache_ttl_seconds == 900
    assert settings.result_ttl_seconds == 86400
    assert settings.max_inline_markdown_bytes == 51200
    assert settings.max_markdown_bytes == 2097152
    assert settings.max_html_bytes == 10485760
    assert settings.database_url is None


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MAX_CONCURRENCY", "10")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@postgres:5432/hermes_crawler")

    settings = Settings(_env_file=None)

    assert settings.mcp_transport == "streamable-http"
    assert settings.max_concurrency == 10
    assert settings.database_url == "postgresql://user:pass@postgres:5432/hermes_crawler"


def test_profile_defaults(monkeypatch):
    for key in [
        "PROFILE_ENCRYPTION_KEY", "PROFILES_DIR",
        "PROFILE_TTL_SECONDS", "MAX_ACTIVE_PROFILES",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.profile_encryption_key is None
    assert settings.profiles_dir == Path("/data/profiles")
    assert settings.profile_ttl_seconds == 2592000  # 30 天
    assert settings.max_active_profiles == 2


def test_profile_env_overrides(monkeypatch):
    monkeypatch.setenv("PROFILE_ENCRYPTION_KEY", "s3cr3t-key")
    monkeypatch.setenv("MAX_ACTIVE_PROFILES", "5")

    settings = Settings(_env_file=None)

    assert settings.profile_encryption_key == "s3cr3t-key"
    assert settings.max_active_profiles == 5


def test_rejects_invalid_transport(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")

    try:
        Settings(_env_file=None)
        assert False, "expected validation error for invalid MCP_TRANSPORT"
    except ValueError:
        pass
