"""京东扫码登录适配器（协议式，Phase 3b / M-P3-4）。

依据 S2/S4 真机验证（设计 §14.1）：不持有浏览器活页面，而是走 JD 的 QR
登录 HTTP 协议——`show`（二维码 + `wlfstk_smdl` token）→ 轮询 `check`
（201 未扫 / 202 已扫待确认 / 200 成功带 ticket）→ `qrCodeTicketValidation`
换 `pt_key`/`pt_pin` 登录 cookie（落在传入 HTTP 会话的 cookie jar 中）。

`http` 是一个持 cookie 的异步 HTTP 会话（curl_cffi AsyncSession 的最小接口：
`await http.get(url, headers=...)` 返回带 `.content`/`.text` 的响应，`http.cookies`
可按名取值）。便于用离线 fake 单测。
"""
import re
import secrets
import time

_SHOW = "https://qr.m.jd.com/show?appid=133&size=200&t={t}"
_CHECK = "https://qr.m.jd.com/check?callback=jQuery{cb}&appid=133&token={token}&_={t}"
_VALIDATE = "https://passport.jd.com/uc/qrCodeTicketValidation?t={ticket}"
_LOGIN_PAGE = "https://passport.jd.com/new/login.aspx"

_CODE_STATUS = {201: "PENDING", 202: "SCANNED", 200: "SUCCESS"}
_EXPIRED_CODES = {203, 257, 176, 4}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _callback_id() -> int:
    return secrets.randbelow(9_000_000) + 1_000_000


class JdLoginAdapter:
    domain_patterns = ("jd.com",)

    async def open_login(self, http, url: str) -> None:
        # baseline：拿基础 cookie，贴近真实浏览器上下文。
        await http.get(_LOGIN_PAGE)

    async def capture_qr(self, http) -> bytes:
        resp = await http.get(
            _SHOW.format(t=_now_ms()),
            headers={"Referer": _LOGIN_PAGE},
        )
        return resp.content  # PNG；wlfstk_smdl 已写入 http.cookies

    async def poll_status(self, http) -> str:
        token = http.cookies.get("wlfstk_smdl")
        resp = await http.get(
            _CHECK.format(cb=_callback_id(), token=token, t=_now_ms()),
            headers={"Referer": "https://passport.jd.com/"},
        )
        body = resp.text
        m = re.search(r'"code"\s*:\s*(\d+)', body)
        code = int(m.group(1)) if m else -1

        if code == 200:
            tm = re.search(r'"ticket"\s*:\s*"([^"]+)"', body)
            ticket = tm.group(1).replace("\\/", "/") if tm else ""
            # 换登录态：登录 cookie（pt_key/pt_pin）写入 http.cookies。
            await http.get(
                _VALIDATE.format(ticket=ticket),
                headers={"Referer": "https://passport.jd.com/"},
            )
            return "SUCCESS"
        if code in _EXPIRED_CODES:
            return "EXPIRED"
        return _CODE_STATUS.get(code, "PENDING")
