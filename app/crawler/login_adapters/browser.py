"""浏览器原生登录适配器（DOM 观察式，Phase 3d / BN1）。

与 HTTP 协议式适配器（jd.py / taobao.py）不同，这里操作一个**活的浏览器 page**：
打开登录页 → 截二维码元素 → 轮询时观察 `page.url` 迁移（跳离登录页=登录成功，
让站点的 JS 终化在浏览器里跑完）与过期标记。选择器/URL 依据 §14.1 真机 spike。
"""


class _QrBrowserAdapter:
    """共享逻辑：poll_status 以 URL 迁移为主 + 可选的过期标记检测。"""

    domain_patterns: tuple[str, ...] = ()
    login_url: str = ""
    _qr_selector: str = ""
    _login_url_markers: tuple[str, ...] = ()
    _expired_selector: str | None = None

    async def open_login(self, page, url: str | None = None) -> None:
        # 浏览器登录固定打开适配器的登录页；忽略调用方传入的 url。
        await page.goto(self.login_url, wait_until="domcontentloaded")

    async def capture_qr(self, page) -> bytes:
        return await page.locator(self._qr_selector).first.screenshot()

    async def poll_status(self, page) -> str:
        if not any(marker in page.url for marker in self._login_url_markers):
            return "SUCCESS"  # 已跳离登录页 → 原生登录完成
        if self._expired_selector is not None:
            try:
                if await page.locator(self._expired_selector).first.is_visible():
                    return "EXPIRED"
            except Exception:  # noqa: BLE001 -- 过期检测尽力而为，失败按 PENDING
                pass
        return "PENDING"


class JdBrowserLoginAdapter(_QrBrowserAdapter):
    domain_patterns = ("jd.com",)
    login_url = "https://passport.jd.com/new/login.aspx"
    _qr_selector = "#passport-main-qrcode-img"
    _login_url_markers = ("passport.jd.com", "login.aspx")
    _expired_selector = "#J-qrcoderror"  # 过期时变可见


class TaobaoBrowserLoginAdapter(_QrBrowserAdapter):
    domain_patterns = ("taobao.com", "tmall.com")
    login_url = "https://login.taobao.com/member/login.jhtml"
    _qr_selector = ".qrcode-img"
    _login_url_markers = ("login.taobao.com", "login.htm", "login.jhtml")
