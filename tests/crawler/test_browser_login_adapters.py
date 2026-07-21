from app.crawler.login_adapters.browser import (
    JdBrowserLoginAdapter,
    TaobaoBrowserLoginAdapter,
)


class FakeLocator:
    def __init__(self, *, shot=b"", visible=False):
        self._shot = shot
        self._visible = visible

    @property
    def first(self):
        return self

    async def screenshot(self, **kwargs):
        return self._shot

    async def is_visible(self):
        return self._visible


class FakePage:
    def __init__(self, *, url="", qr=b"QRPNG", locators=None):
        self.url = url
        self.qr = qr
        self.goto_calls = []
        self._locators = locators or {}

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    def locator(self, sel):
        if sel in self._locators:
            return self._locators[sel]
        return FakeLocator(shot=self.qr)


# --- 通用契约 ---

def test_domain_patterns():
    assert JdBrowserLoginAdapter().domain_patterns == ("jd.com",)
    assert TaobaoBrowserLoginAdapter().domain_patterns == ("taobao.com", "tmall.com")


async def test_open_login_navigates_to_login_url():
    page = FakePage()
    a = TaobaoBrowserLoginAdapter()
    await a.open_login(page)
    assert page.goto_calls == [a.login_url]


async def test_capture_qr_screenshots_qr_element():
    page = FakePage(qr=b"PNGDATA")
    qr = await JdBrowserLoginAdapter().capture_qr(page)
    assert qr == b"PNGDATA"


# --- poll_status：以 URL 迁移为主 ---

async def test_poll_pending_while_on_login_page():
    page = FakePage(url="https://login.taobao.com/member/login.jhtml")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "PENDING"


async def test_poll_success_when_navigated_away():
    page = FakePage(url="https://i.taobao.com/my_taobao.htm")
    assert await TaobaoBrowserLoginAdapter().poll_status(page) == "SUCCESS"


async def test_jd_poll_success_when_left_passport():
    page = FakePage(url="https://www.jd.com/")
    assert await JdBrowserLoginAdapter().poll_status(page) == "SUCCESS"


async def test_jd_poll_expired_when_error_marker_visible():
    # JD 二维码过期时 #J-qrcoderror 变为可见
    page = FakePage(
        url="https://passport.jd.com/new/login.aspx",
        locators={"#J-qrcoderror": FakeLocator(visible=True)},
    )
    assert await JdBrowserLoginAdapter().poll_status(page) == "EXPIRED"


async def test_jd_poll_pending_when_error_hidden():
    page = FakePage(
        url="https://passport.jd.com/new/login.aspx",
        locators={"#J-qrcoderror": FakeLocator(visible=False)},
    )
    assert await JdBrowserLoginAdapter().poll_status(page) == "PENDING"
