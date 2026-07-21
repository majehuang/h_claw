import pytest

from app.crawler.stealth_fetcher import fetch_stealth
from app.security.url_validator import URLValidationError

pytestmark = pytest.mark.asyncio


class FakeResponse:
    def __init__(self, url, status=200, html="<html><body>ok</body></html>"):
        self.url = url
        self.status = status
        self.html_content = html


class FakePool:
    def __init__(self, response=None):
        self._response = response
        self.stealth_calls: list[str] = []
        self.fetch_kwargs: list[dict] = []

    async def fetch_stealth(self, url, **kwargs):
        self.stealth_calls.append(url)
        self.fetch_kwargs.append(kwargs)
        return self._response or FakeResponse(url)


def _ok_validate(url: str) -> None:
    return None


async def test_fetches_via_stealth_session():
    pool = FakePool(FakeResponse("https://shop.example.com/p/1"))

    result = await fetch_stealth(
        "https://shop.example.com/p/1", pool=pool, validate=_ok_validate
    )

    assert result.status_code == 200
    assert pool.stealth_calls == ["https://shop.example.com/p/1"]


async def test_enables_cloudflare_solving_by_default():
    pool = FakePool()

    await fetch_stealth("https://shop.example.com/p/1", pool=pool, validate=_ok_validate)

    assert pool.fetch_kwargs[0]["solve_cloudflare"] is True


async def test_uses_stealth_timeout_and_one_extra_retry():
    pool = FakePool()

    await fetch_stealth(
        "https://shop.example.com/p/1",
        pool=pool,
        validate=_ok_validate,
        timeout_seconds=90,
    )

    kwargs = pool.fetch_kwargs[0]
    assert kwargs["timeout"] == 90000
    # 第 7.3 节：stealth 模式最多额外重试一次。
    assert kwargs["retries"] == 1


class FakeProfileSession:
    def __init__(self, response=None):
        self.calls: list[str] = []
        self._response = response

    async def fetch(self, url, **kwargs):
        self.calls.append(url)
        return self._response or FakeResponse(url)


async def test_uses_provided_session_over_pool():
    # A4：传入 profile 浏览器会话时，走该会话（带登录态 cookie），绕过无状态池。
    pool = FakePool()
    session = FakeProfileSession(FakeResponse("https://shop.example.com/p/1"))

    result = await fetch_stealth(
        "https://shop.example.com/p/1",
        pool=pool,
        validate=_ok_validate,
        session=session,
    )

    assert result.status_code == 200
    assert session.calls == ["https://shop.example.com/p/1"]
    assert pool.stealth_calls == []  # 未走无状态池


async def test_validates_final_url():
    pool = FakePool(FakeResponse("http://10.0.0.1/internal"))

    def _validate(url: str) -> None:
        if "10.0.0.1" in url:
            raise URLValidationError("SSRF_BLOCKED", "内网地址")

    with pytest.raises(Exception) as exc_info:
        await fetch_stealth("https://shop.example.com/p/1", pool=pool, validate=_validate)

    assert getattr(exc_info.value, "error_code", None) == "SSRF_BLOCKED"
