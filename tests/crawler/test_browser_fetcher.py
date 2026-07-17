import pytest

from app.crawler.browser_fetcher import fetch_browser
from app.crawler.http_fetcher import FetchError
from app.security.url_validator import URLValidationError

pytestmark = pytest.mark.asyncio


class FakeResponse:
    def __init__(self, url, status=200, html="<html><body>ok</body></html>"):
        self.url = url
        self.status = status
        self.html_content = html


class FakePool:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.dynamic_calls: list[str] = []
        self.fetch_kwargs: list[dict] = []

    async def fetch_dynamic(self, url, **kwargs):
        self.dynamic_calls.append(url)
        self.fetch_kwargs.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response or FakeResponse(url)


def _ok_validate(url: str) -> None:
    return None


async def test_fetches_via_dynamic_session_and_maps_response():
    pool = FakePool(FakeResponse("https://shop.example.com/p/1", status=200))

    result = await fetch_browser(
        "https://shop.example.com/p/1", pool=pool, validate=_ok_validate
    )

    assert result.status_code == 200
    assert result.final_url == "https://shop.example.com/p/1"
    assert result.request_url == "https://shop.example.com/p/1"
    assert "ok" in result.html
    assert pool.dynamic_calls == ["https://shop.example.com/p/1"]


async def test_validates_initial_url_before_fetching():
    pool = FakePool()

    def _reject(url: str) -> None:
        raise URLValidationError("SSRF_BLOCKED", "禁止访问内网")

    with pytest.raises(FetchError) as exc_info:
        await fetch_browser("https://shop.example.com/p/1", pool=pool, validate=_reject)

    assert exc_info.value.error_code == "SSRF_BLOCKED"
    assert pool.dynamic_calls == []  # 校验失败时不应真正发起抓取


async def test_validates_final_url_after_redirect():
    # 浏览器内部跟随重定向，最终落到内网地址，final_url 必须被重新校验。
    pool = FakePool(FakeResponse("http://169.254.169.254/latest/meta-data"))
    checked: list[str] = []

    def _validate(url: str) -> None:
        checked.append(url)
        if "169.254.169.254" in url:
            raise URLValidationError("SSRF_BLOCKED", "元数据地址")

    with pytest.raises(FetchError) as exc_info:
        await fetch_browser("https://shop.example.com/p/1", pool=pool, validate=_validate)

    assert exc_info.value.error_code == "SSRF_BLOCKED"
    assert "https://shop.example.com/p/1" in checked
    assert "http://169.254.169.254/latest/meta-data" in checked


async def test_passes_wait_and_timeout_kwargs_to_pool():
    pool = FakePool()

    await fetch_browser(
        "https://shop.example.com/p/1",
        pool=pool,
        validate=_ok_validate,
        timeout_seconds=60,
        wait_selector=".price",
    )

    kwargs = pool.fetch_kwargs[0]
    assert kwargs["timeout"] == 60000  # 秒 -> 毫秒
    assert kwargs["wait_selector"] == ".price"
    assert kwargs["network_idle"] is True


async def test_session_param_is_accepted_but_unused_in_phase_one():
    # 第 14.4 节：抓取函数从第一期就预留 session 占位，恒为 None。
    pool = FakePool()
    result = await fetch_browser(
        "https://shop.example.com/p/1", pool=pool, validate=_ok_validate, session=None
    )
    assert result.status_code == 200
