from app.crawler.login_adapters.browser import (
    JdBrowserLoginAdapter,
    TaobaoBrowserLoginAdapter,
)


class FakeLocator:
    def __init__(self, *, shot=b"", visible=False, shots=None):
        self._shot = shot
        self._visible = visible
        # 依次返回的截图序列（模拟异步换图过程），用完后固定返回最后一张。
        self._shots = list(shots) if shots is not None else None
        self.screenshot_calls = 0

    @property
    def first(self):
        return self

    async def screenshot(self, **kwargs):
        self.screenshot_calls += 1
        if self._shots is not None:
            idx = min(self.screenshot_calls - 1, len(self._shots) - 1)
            return self._shots[idx]
        return self._shot

    async def is_visible(self):
        return self._visible

    async def wait_for(self, **kwargs):
        return None


class FakePage:
    def __init__(self, *, url="", qr=b"QRPNG", locators=None):
        self.url = url
        self.qr = qr
        self.goto_calls = []
        self._locators = locators or {}

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    async def wait_for_timeout(self, ms):
        return None

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


async def test_capture_qr_waits_for_screenshot_to_stabilize():
    # 登录页二维码图片在最终定型前可能经历几次重绘（占位图/加载动画/换图），
    # 必须等连续两次截图内容一致才收下最终这张，不能提前截到过渡态
    # （HC-QR-2 回归用例）。注意：这只防"还在变化"，防不了"一开始就静止不动
    # 的错误图片"——那需要按二维码内容校验域名，这里没做。
    adapter = JdBrowserLoginAdapter()
    locator = FakeLocator(shots=[b"LOADING_1", b"LOADING_2", b"REAL_QR", b"REAL_QR"])
    page = FakePage(locators={adapter._qr_selector: locator})

    qr = await adapter.capture_qr(page)

    assert qr == b"REAL_QR"
    assert locator.screenshot_calls == 4  # 首截 + 3 次重截才等到连续两次一致


async def test_capture_qr_gives_up_after_max_attempts_if_never_stable():
    # 极端情况：图片一直在变，超过重试上限后返回最后一张，而不是无限等待。
    adapter = JdBrowserLoginAdapter()
    shots = [f"F{i}".encode() for i in range(10)]  # 每次都不同，永不稳定
    locator = FakeLocator(shots=shots)
    page = FakePage(locators={adapter._qr_selector: locator})

    qr = await adapter.capture_qr(page)

    assert qr == shots[5]  # 1(首截) + 5(重试上限) 次调用后的最后一张
    assert locator.screenshot_calls == 6


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
