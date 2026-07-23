"""扫码登录 MCP 工具实现层（Phase 3b / M-P3-5）。

三个工具围绕 LoginManager 的两阶段协议（见设计 §5.2）：
- begin_login：打开登录页、返回二维码（base64）与 login_id；
- poll_login：轮询扫码状态，成功返回可复用的 session_id；
- cancel_login：放弃登录、释放资源。
"""
import base64
from typing import Any
from urllib.parse import urlsplit

from app.crawler.login_manager import LoginError, LoginSession, LoginState
from app.crawler.qr_render import QRDecodeError, decode_qr_payload, render_ascii_qr


def _login_response(login: LoginSession) -> dict[str, Any]:
    resp: dict[str, Any] = {
        "login_id": login.login_id,
        "status": login.status,
        "domain": login.domain,
    }
    if login.qr_png is not None:
        resp["qr_png_base64"] = base64.b64encode(login.qr_png).decode("ascii")
    if login.session_id is not None:
        resp["session_id"] = login.session_id
    if login.expires_at is not None:
        resp["expires_at"] = login.expires_at.isoformat()
    return resp


def _disabled() -> dict[str, Any]:
    return {
        "status": "FAILED",
        "error_code": "LOGIN_INIT_FAILED",
        "error_message": "登录功能未启用（未配置 PROFILE_ENCRYPTION_KEY）。",
    }


def _not_found(login_id: str) -> dict[str, Any]:
    return {
        "status": "FAILED",
        "error_code": "LOGIN_NOT_FOUND",
        "error_message": f"登录会话 {login_id} 不存在或已结束。",
    }


async def begin_login_impl(service: Any, *, url: str) -> dict[str, Any]:
    if service.login_manager is None:
        return _disabled()
    try:
        login = await service.login_manager.begin(url)
    except LoginError as exc:
        return {"status": "FAILED", "error_code": exc.error_code, "error_message": str(exc)}
    return _login_response(login)


async def poll_login_impl(service: Any, *, login_id: str) -> dict[str, Any]:
    if service.login_manager is None:
        return _disabled()
    login = await service.login_manager.poll(login_id)
    if login is None:
        return _not_found(login_id)
    return _login_response(login)


async def cancel_login_impl(service: Any, *, login_id: str) -> dict[str, Any]:
    if service.login_manager is None:
        return _disabled()
    cancelled = await service.login_manager.cancel(login_id)
    if not cancelled:
        return _not_found(login_id)
    return {"status": LoginState.CANCELLED, "login_id": login_id}


def _registrable_domain(host: str) -> str:
    parts = (host or "").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "").lower()


def _same_registrable_domain(payload_url: str, login_domain: str) -> bool:
    payload_host = urlsplit(payload_url).hostname or ""
    if not payload_host:
        return False
    return _registrable_domain(payload_host) == _registrable_domain(login_domain)


async def render_qr_terminal_impl(service: Any, *, login_id: str) -> dict[str, Any]:
    """把二维码截图解码、重编码成可直接粘贴进回复的终端文本二维码（HC-QR-3）。

    附带一个尽力而为的安全检查：把二维码里解出来的 URL 域名和发起登录时的
    页面域名比对（同注册域名），不一致时打上 `domain_mismatch` 标记——曾实测
    截到过与登录站点完全无关的二维码（见 capture_qr 的截图稳定性修复），
    这里再兜底一层，让调用方能在展示给用户前发现问题。
    """
    if service.login_manager is None:
        return _disabled()
    login = service.login_manager.get_qr_entry(login_id)
    if login is None or login.qr_png is None:
        return _not_found(login_id)
    try:
        payload = decode_qr_payload(login.qr_png)
    except QRDecodeError as exc:
        return {"status": "FAILED", "error_code": "QR_DECODE_FAILED", "error_message": str(exc)}

    resp: dict[str, Any] = {
        "status": "SUCCESS",
        "login_id": login_id,
        "ascii_qr": render_ascii_qr(payload),
    }
    if not _same_registrable_domain(payload, login.domain):
        resp["domain_mismatch"] = True
        resp["warning"] = (
            f"解码出的二维码内容域名与登录域名 {login.domain} 不一致，"
            "可能截到了错误的图片（如广告/占位图）。不要展示给用户，"
            "改为重新调用 begin_login 拿一张新的。"
        )
    return resp
