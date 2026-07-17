import pytest

from app.crawler.browser_fetcher import fetch_browser
from app.crawler.browser_pool import BrowserPool
from app.crawler.stealth_fetcher import fetch_stealth

pytestmark = [pytest.mark.asyncio, pytest.mark.browser]


def _no_op_validate(url: str) -> None:
    # 本地测试服务器跑在 127.0.0.1，真实 SSRF 校验会拒绝，集成测试里放行。
    return None


async def test_real_browser_pool_fetches_local_page(local_server):
    pool = BrowserPool(max_browser_pages=1, restart_after_tasks=100)
    await pool.start()
    try:
        result = await fetch_browser(
            f"{local_server}/ok", pool=pool, validate=_no_op_validate, timeout_seconds=30
        )
        assert result.status_code == 200
        assert result.final_url == f"{local_server}/ok"
        assert "hello" in result.html
        assert pool.stats()["task_count"] == 1
    finally:
        await pool.close()


async def test_real_stealth_session_fetches_local_page(local_server):
    # StealthyFetcher（patchright chromium）第三层，验证与 DynamicFetcher
    # 共用浏览器二进制、可独立启动抓取。
    pool = BrowserPool(max_browser_pages=1, restart_after_tasks=100)
    await pool.start()
    try:
        result = await fetch_stealth(
            f"{local_server}/ok", pool=pool, validate=_no_op_validate, timeout_seconds=30
        )
        assert result.status_code == 200
        assert "hello" in result.html
    finally:
        await pool.close()
