"""浏览器原生登录适配器（DOM 观察式，Phase 3d / BN1，HC-011 强化）。

与 HTTP 协议式适配器不同，这里操作一个**活的浏览器 page**：打开登录页 → 截二维码
元素 → 轮询时观察 `page.url` 迁移。HC-011 起，「跳离登录页」不再直接等同登录成功：
还必须（1）最终 host 属于该站点允许列表，（2）不是安全验证/挑战中间页，（3）登录态
DOM（若配置）已出现。只有全部满足才回 SUCCESS，从而只在验证通过后才封存 profile；
跳到滑块/安全页/第三方域名不会误创建 ACTIVE profile。
"""
import logging
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# 二维码稳定性重截（HC-QR-2）：站点登录页常先渲染占位/广告图，异步替换成真正的
# 登录二维码——曾实测截到过京东登录页里的第三方推广二维码。等元素可见后连续两次
# 截图字节相同才认为已稳定，最多重截这么多次（每次间隔见下），避免截到过渡态。
_QR_STABILITY_MAX_ATTEMPTS = 5
_QR_STABILITY_INTERVAL_MS = 800


def _host_allowed(host: str, allow: tuple[str, ...]) -> bool:
    host = (host or "").lower()
    return any(host == d or host.endswith(f".{d}") for d in allow)


class _QrBrowserAdapter:
    """共享逻辑：poll_status 以 URL 迁移为主，叠加 host 允许列表 + 安全页/挑战 + 登录态 DOM。"""

    domain_patterns: tuple[str, ...] = ()
    login_url: str = ""
    _qr_selector: str = ""
    _login_url_markers: tuple[str, ...] = ()
    _expired_selector: str | None = None
    # HC-011：登录成功后允许落地的业务 host（registrable domain 后缀匹配）。
    _success_hosts: tuple[str, ...] = ()
    # 安全验证/异常校验中间页标记：跳离登录页但仍在这些页上时按 PENDING（用户尚未完成）。
    _security_url_markers: tuple[str, ...] = ()
    # 登录态 DOM 证据选择器；配置后必须可见才算成功，None 则跳过这一项。
    _logged_in_selector: str | None = None

    async def open_login(self, page, url: str | None = None) -> None:
        # 浏览器登录固定打开适配器的登录页；忽略调用方传入的 url。
        await page.goto(self.login_url, wait_until="domcontentloaded")

    async def capture_qr(self, page) -> bytes:
        # 二维码由 JS 异步渲染，等元素可见并留缓冲再截，避免截到未加载完的码。
        locator = page.locator(self._qr_selector).first
        await locator.wait_for(state="visible", timeout=15_000)
        await page.wait_for_timeout(1500)
        shot = await locator.screenshot()
        # 同一 DOM 位置可能先展示占位/广告图，再异步换成真正的登录二维码；
        # 连续两次截图内容一致才收，否则继续等它稳定下来（HC-QR-2）。
        for _ in range(_QR_STABILITY_MAX_ATTEMPTS):
            await page.wait_for_timeout(_QR_STABILITY_INTERVAL_MS)
            next_shot = await locator.screenshot()
            if next_shot == shot:
                return shot
            shot = next_shot
        return shot

    async def _visible(self, page, selector: str) -> bool:
        try:
            return await page.locator(selector).first.is_visible()
        except Exception:  # noqa: BLE001 -- DOM 探测尽力而为
            return False

    async def poll_status(self, page) -> str:
        url = page.url or ""
        parsed = urlsplit(url)
        # 诊断用（HC-QR-5）：只记 host/path，不记 query string——登录跳转的
        # query 里常带 ticket/token 类参数，不能整条 URL 落日志。
        logger.info(
            "login poll_status host=%s path=%s",
            parsed.hostname or "",
            parsed.path or "",
        )
        # 仍在登录页：检查过期，否则等待扫码。
        if any(marker in url for marker in self._login_url_markers):
            if self._expired_selector is not None and await self._visible(
                page, self._expired_selector
            ):
                return "EXPIRED"
            return "PENDING"

        # 已跳离登录页，但不再直接判成功（HC-011）。
        # 安全验证/异常校验中间页：用户还需继续操作，保持等待。
        if any(marker in url for marker in self._security_url_markers):
            return "PENDING"

        # 落到非允许 host（第三方/外部域名）→ 硬失败，不封存 profile（UT-030）。
        host = urlsplit(url).hostname or ""
        if self._success_hosts and not _host_allowed(host, self._success_hosts):
            return "FAILED"

        # 登录态 DOM 证据（若配置）必须出现，否则继续等待。
        if self._logged_in_selector is not None and not await self._visible(
            page, self._logged_in_selector
        ):
            return "PENDING"

        return "SUCCESS"


class JdBrowserLoginAdapter(_QrBrowserAdapter):
    domain_patterns = ("jd.com",)
    login_url = "https://passport.jd.com/new/login.aspx"
    _qr_selector = "#passport-main-qrcode-img"
    _login_url_markers = ("passport.jd.com", "login.aspx")
    _expired_selector = "#J-qrcoderror"  # 过期时变可见
    _success_hosts = ("jd.com", "jd.hk")
    _security_url_markers = ("safe.jd.com", "verify", "security", "risk")


class TaobaoBrowserLoginAdapter(_QrBrowserAdapter):
    domain_patterns = ("taobao.com", "tmall.com")
    login_url = "https://login.taobao.com/member/login.jhtml"
    _qr_selector = ".qrcode-img"
    _login_url_markers = ("login.taobao.com", "login.htm", "login.jhtml")
    _success_hosts = ("taobao.com", "tmall.com")
    _security_url_markers = ("sec.taobao.com", "security-check", "havana", "unusual")
