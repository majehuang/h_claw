"""HC-011：强化登录成功验证（UT-028 / UT-029 / UT-030）。

「跳离登录页」不再等同成功：必须落到允许 host、非安全验证/挑战中间页、
且登录态 DOM（若配置）出现，才回 SUCCESS，从而只在验证通过后封存 profile。
"""
import pytest

from app.crawler.browser_login import close_browser_login  # noqa: F401 (契约引用)
from app.crawler.login_adapters.browser import (
    JdBrowserLoginAdapter,
    TaobaoBrowserLoginAdapter,
    _QrBrowserAdapter,
)

pytestmark = pytest.mark.asyncio


class FakeLocator:
    def __init__(self, visible=False):
        self._visible = visible

    @property
    def first(self):
        return self

    async def is_visible(self):
        return self._visible


class FakePage:
    def __init__(self, url, locators=None):
        self.url = url
        self._locators = locators or {}

    def locator(self, sel):
        return self._locators.get(sel, FakeLocator(visible=False))


# --- UT-028 跳离登录页但进入安全验证页 → 不算成功 ---
async def test_security_page_is_not_success():
    page = FakePage("https://sec.taobao.com/security-check?uid=1")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "PENDING"


async def test_security_marker_on_business_host_still_pending():
    # 即便 host 属于 taobao.com，只要命中安全验证标记，也不判成功。
    page = FakePage("https://login.taobao.com/havana/verify")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "PENDING"


# --- UT-029 正常登录成功 ---
async def test_navigated_to_allowed_business_host_is_success():
    page = FakePage("https://i.taobao.com/my_taobao.htm")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "SUCCESS"


async def test_logged_in_dom_required_when_configured():
    class WithDom(_QrBrowserAdapter):
        _login_url_markers = ("login.example.com",)
        _success_hosts = ("example.com",)
        _logged_in_selector = ".user-nav"

    adapter = WithDom()
    # 落到允许 host 但登录态 DOM 未出现 → 继续等待。
    page_no_dom = FakePage("https://www.example.com/home")
    assert await adapter.poll_status(page_no_dom) == "PENDING"
    # 登录态 DOM 出现 → 成功。
    page_dom = FakePage(
        "https://www.example.com/home", locators={".user-nav": FakeLocator(visible=True)}
    )
    assert await adapter.poll_status(page_dom) == "SUCCESS"


# --- UT-030 跳转到非允许域名 → 失败 ---
async def test_external_domain_is_failure():
    page = FakePage("https://evil.example.com/landing")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "FAILED"


async def test_third_party_host_not_in_allowlist_fails():
    page = FakePage("https://accounts.google.com/o/oauth2")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "FAILED"


# --- 回归：登录不稳定的两个成因（见 HC-011 修复） ---

@pytest.mark.parametrize("adapter", [JdBrowserLoginAdapter(), TaobaoBrowserLoginAdapter()])
@pytest.mark.parametrize("url", ["about:blank", "", "data:text/html,x"])
async def test_navigation_in_flight_is_pending_not_failed(adapter, url):
    """导航未落地（about:blank / 空 URL / 非 http scheme）必须 PENDING。

    判 FAILED 会让 LoginManager 立刻收尾并关闭上下文，直接杀死本次登录——
    由于 page.url 在跳转途中短暂为 about:blank，这会表现为"时好时坏登不上"。
    """
    assert await adapter.poll_status(FakePage(url)) == "PENDING"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.jd.com/?from=verify",       # query 里含 verify
        "https://item.jd.com/123.html?risk=0",   # query 里含 risk
        "https://order.jd.com/center/list.action",
    ],
)
async def test_query_string_does_not_trigger_security_false_positive(url):
    """安全页判定只看 host+path：query 里的 verify/risk 不得把已登录页卡成 PENDING。"""
    assert await JdBrowserLoginAdapter().poll_status(FakePage(url)) == "SUCCESS"


async def test_taobao_query_marker_does_not_block_success():
    page = FakePage("https://www.taobao.com/?spm=a21bo.unusual")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "SUCCESS"


async def test_real_security_host_and_path_still_pending():
    """真正的安全页（host 或 path 命中）仍必须 PENDING，不能因修复而放行。"""
    assert await JdBrowserLoginAdapter().poll_status(
        FakePage("https://safe.jd.com/dialog/handler.action")
    ) == "PENDING"
    assert await JdBrowserLoginAdapter().poll_status(
        FakePage("https://passport.jd.com/verify/step")
    ) == "PENDING"
