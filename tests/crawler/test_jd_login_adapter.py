import pytest

from app.crawler.login_adapters.jd import JdLoginAdapter

pytestmark = pytest.mark.asyncio


class FakeResp:
    def __init__(self, content=b"", text=""):
        self.content = content
        self.text = text


class FakeHttp:
    """模拟持 cookie 的 HTTP 会话（curl_cffi AsyncSession 的最小接口）。"""

    def __init__(self, *, check_text="", show_content=b"PNG"):
        self.cookies = {"wlfstk_smdl": "TOK123"}
        self.calls = []
        self._check_text = check_text
        self._show_content = show_content

    async def get(self, url, headers=None):
        self.calls.append(url)
        if "/show" in url:
            return FakeResp(content=self._show_content)
        if "/check" in url:
            return FakeResp(text=self._check_text)
        if "qrCodeTicketValidation" in url:
            return FakeResp(text="{}")
        return FakeResp()


def test_domain_patterns():
    assert JdLoginAdapter().domain_patterns == ("jd.com",)


async def test_capture_qr_returns_show_png():
    http = FakeHttp(show_content=b"PNGDATA")
    qr = await JdLoginAdapter().capture_qr(http)
    assert qr == b"PNGDATA"
    assert any("qr.m.jd.com/show" in u for u in http.calls)


async def test_poll_pending():
    http = FakeHttp(check_text='jQuery1({"code" : 201,"msg" : "二维码未扫描"})')
    assert await JdLoginAdapter().poll_status(http) == "PENDING"


async def test_poll_scanned():
    http = FakeHttp(check_text='jQuery1({"code" : 202,"msg" : "请手机客户端确认登录"})')
    assert await JdLoginAdapter().poll_status(http) == "SCANNED"


async def test_poll_success_runs_ticket_validation():
    http = FakeHttp(check_text='jQuery1({"code" : 200,"ticket" : "T-abc123"})')
    status = await JdLoginAdapter().poll_status(http)
    assert status == "SUCCESS"
    # 成功时应换取登录态：带 ticket 调 qrCodeTicketValidation
    assert any("qrCodeTicketValidation" in u and "T-abc123" in u for u in http.calls)


async def test_poll_expired():
    http = FakeHttp(check_text='jQuery1({"code" : 203,"msg" : "二维码已失效"})')
    assert await JdLoginAdapter().poll_status(http) == "EXPIRED"
