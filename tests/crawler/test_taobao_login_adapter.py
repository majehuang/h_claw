from app.crawler.login_adapters.taobao import TaobaoLoginAdapter


class FakeResp:
    def __init__(self, content=b"", text=""):
        self.content = content
        self.text = text


class FakeHttp:
    def __init__(self, *, generate="", check="", qr=b"QRPNG"):
        self.calls = []
        self._generate = generate
        self._check = check
        self._qr = qr

    async def get(self, url, headers=None):
        self.calls.append(url)
        if "generateQRCode4Login" in url:
            return FakeResp(text=self._generate)
        if "qrcodeLoginCheck" in url:
            return FakeResp(text=self._check)
        if "alicdn.com" in url or url.endswith(".png"):
            return FakeResp(content=self._qr)
        return FakeResp(text="{}")  # 完成登录 URL


_GEN = '{"lgToken":"LG123","success":true,"url":"//img.alicdn.com/x_xcode.png"}'


def test_domain_patterns():
    assert TaobaoLoginAdapter().domain_patterns == ("taobao.com", "tmall.com")


async def test_capture_qr_fetches_image_and_stores_token():
    http = FakeHttp(generate=_GEN, qr=b"PNGDATA")
    qr = await TaobaoLoginAdapter().capture_qr(http)
    assert qr == b"PNGDATA"
    assert any("generateQRCode4Login" in u for u in http.calls)
    assert any("alicdn.com" in u for u in http.calls)  # 抓了二维码图片
    assert http._tb_lgtoken == "LG123"                 # lgToken 存在会话句柄上（每会话隔离）


async def test_poll_pending():
    http = FakeHttp(check='{"code":"10000","message":"login start state"}')
    http._tb_lgtoken = "LG123"
    assert await TaobaoLoginAdapter().poll_status(http) == "PENDING"


async def test_poll_scanned():
    http = FakeHttp(check='{"code":"10001","message":"scan success"}')
    http._tb_lgtoken = "LG123"
    assert await TaobaoLoginAdapter().poll_status(http) == "SCANNED"


async def test_poll_success_completes_login():
    http = FakeHttp(check='{"code":"10006","url":"//login.taobao.com/member/vst.htm?st=TICK"}')
    http._tb_lgtoken = "LG123"
    status = await TaobaoLoginAdapter().poll_status(http)
    assert status == "SUCCESS"
    # 成功时应 GET 完成登录 URL（设置登录 cookie）
    assert any("vst.htm" in u and "TICK" in u for u in http.calls)


async def test_poll_expired():
    http = FakeHttp(check='{"code":"10004","message":"expired"}')
    http._tb_lgtoken = "LG123"
    assert await TaobaoLoginAdapter().poll_status(http) == "EXPIRED"
