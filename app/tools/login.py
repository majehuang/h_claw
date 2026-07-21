"""扫码登录 MCP 工具实现层（Phase 3b / M-P3-5）。

三个工具围绕 LoginManager 的两阶段协议（见设计 §5.2）：
- begin_login：打开登录页、返回二维码（base64）与 login_id；
- poll_login：轮询扫码状态，成功返回可复用的 session_id；
- cancel_login：放弃登录、释放资源。
"""
import base64
from typing import Any

from app.crawler.login_manager import LoginError, LoginSession, LoginState


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
