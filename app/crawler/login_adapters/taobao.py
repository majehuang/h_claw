"""淘宝/天猫扫码登录适配器（协议式，Phase 3c / M-P3-4）。

依据 spike 实测：`generateQRCode4Login` 返回 `lgToken` + 二维码图片 URL；轮询
`qrcodeLoginCheck` 的 `code`——10000 未扫 / 10001 已扫待确认 / 10006 确认成功
（带完成登录 url）/ 10004 失效。成功后 GET 该 url 设置登录 cookie。

`lgToken` 非 cookie（来自 generate 的 JSON），存在**每会话的 http 句柄**上，避免
共享的适配器实例在并发登录间串号。
"""
import json

_LOGIN_PAGE = "https://login.taobao.com/member/login.jhtml"
_GENERATE = (
    "https://qrlogin.taobao.com/qrcodelogin/generateQRCode4Login.do"
    "?from=tb&appName=taobao&appEntrance=taobao"
)
_CHECK = (
    "https://qrlogin.taobao.com/qrcodelogin/qrcodeLoginCheck.do"
    "?lgToken={lg}&defaulturl=https%3A%2F%2Fwww.taobao.com"
)

_CODE_STATUS = {"10000": "PENDING", "10001": "SCANNED", "10006": "SUCCESS"}
_EXPIRED_CODES = {"10004", "10005"}


def _abs_url(url: str) -> str:
    return f"https:{url}" if url.startswith("//") else url


class TaobaoLoginAdapter:
    domain_patterns = ("taobao.com", "tmall.com")

    async def open_login(self, http, url: str) -> None:
        await http.get(_LOGIN_PAGE)  # baseline cookie

    async def capture_qr(self, http) -> bytes:
        data = json.loads((await http.get(
            _GENERATE, headers={"Referer": _LOGIN_PAGE}
        )).text)
        http._tb_lgtoken = data["lgToken"]  # 每会话隔离
        resp = await http.get(_abs_url(data["url"]), headers={"Referer": _LOGIN_PAGE})
        return resp.content

    async def poll_status(self, http) -> str:
        lg = getattr(http, "_tb_lgtoken", "")
        data = json.loads((await http.get(
            _CHECK.format(lg=lg), headers={"Referer": _LOGIN_PAGE}
        )).text)
        code = str(data.get("code", ""))

        if code == "10006":
            complete_url = data.get("url", "")
            if complete_url:
                # GET 完成登录：设置 _tb_token_ / cookie2 / unb 等登录 cookie。
                await http.get(_abs_url(complete_url), headers={"Referer": _LOGIN_PAGE})
            return "SUCCESS"
        if code in _EXPIRED_CODES:
            return "EXPIRED"
        return _CODE_STATUS.get(code, "PENDING")
