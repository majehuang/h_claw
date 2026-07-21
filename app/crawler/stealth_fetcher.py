from collections.abc import Callable
from typing import Any

from app.crawler.browser_fetch_common import fetch_via_browser
from app.crawler.detector import FetchResponse
from app.security.url_validator import validate_public_http_url


async def fetch_stealth(
    url: str,
    *,
    pool: Any,
    timeout_seconds: int = 90,
    validate: Callable[[str], None] = validate_public_http_url,
    session: Any = None,
) -> FetchResponse:
    """第三层：StealthyFetcher（更一致的浏览器指纹 + Cloudflare 挑战处理）。

    第 7.3 节：适用于浏览器自动化检测、Cloudflare 等挑战页面；stealth 模式
    最多额外重试一次，禁止无限尝试。
    """
    extra_kwargs: dict[str, Any] = {
        "solve_cloudflare": True,
        "retries": 1,
    }

    return await fetch_via_browser(
        url,
        pool_fetch=pool.fetch_stealth,
        timeout_seconds=timeout_seconds,
        validate=validate,
        extra_kwargs=extra_kwargs,
        session=session,
    )
