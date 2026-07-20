from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    data_dir: Path = Path("/data")

    max_concurrency: int = 5
    max_browser_pages: int = 3
    max_per_domain: int = 1

    http_timeout_seconds: int = 15
    browser_timeout_seconds: int = 60
    stealth_timeout_seconds: int = 90

    cache_ttl_seconds: int = 900
    result_ttl_seconds: int = 86400
    max_inline_markdown_bytes: int = 51200
    max_markdown_bytes: int = 2097152
    max_html_bytes: int = 10485760

    database_url: str | None = None

    # Phase 3a — 持久 Profile（见 phase-3 设计 §4.2.1 / §15.1）
    # 主密钥从部署环境注入，绝不进镜像/日志/Git/data 卷；未配置时 profile 功能不可用。
    profile_encryption_key: str | None = None
    profiles_dir: Path = Path("/data/profiles")
    profile_ttl_seconds: int = 2592000  # 30 天
    max_active_profiles: int = 2
