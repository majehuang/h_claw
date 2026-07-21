from collections.abc import Callable
from typing import Any

from app.crawler.browser_fetch_common import fetch_via_browser
from app.crawler.detector import FetchResponse
from app.security.url_validator import validate_public_http_url


async def fetch_browser(
    url: str,
    *,
    pool: Any,
    timeout_seconds: int = 60,
    wait_selector: str | None = None,
    validate: Callable[[str], None] = validate_public_http_url,
    session: Any = None,
    cookies: dict[str, str] | None = None,
) -> FetchResponse:
    """第二层：DynamicFetcher（Chromium 执行 JavaScript）。

    等待 DOMContentLoaded 与网络空闲，必要时等待商品相关元素出现
    （wait_selector），再取渲染后的 DOM（第 7.2 节）。
    """
    extra_kwargs: dict[str, Any] = {}
    if wait_selector is not None:
        extra_kwargs["wait_selector"] = wait_selector

    return await fetch_via_browser(
        url,
        pool_fetch=pool.fetch_dynamic,
        timeout_seconds=timeout_seconds,
        validate=validate,
        extra_kwargs=extra_kwargs,
        session=session,
        cookies=cookies,
    )
