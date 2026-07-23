"""扫码登录的在途会话状态机与注册表（Phase 3b / M-P3-3）。

MCP 一问一答，而扫码是几十秒的异步过程，故拆成 begin/poll/cancel（见设计
§5.1–§5.3）：begin 打开登录页并抓二维码、把活的登录会话挂入注册表；poll 驱动
站点适配器读取扫码状态；成功则回写密文并返回可复用的 `session_id`。

持有「活的登录浏览器会话」这类有状态资源经注入的 `session_opener` /
`session_closer` 抽象，便于单测与后续接入 ProfileManager。
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from app.crawler.login_adapters.base import select_adapter


class LoginError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


class LoginState:
    CREATED = "CREATED"
    QR_READY = "QR_READY"
    SCANNED = "SCANNED"
    SUCCESS = "SUCCESS"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# 适配器 poll_status 原始信号 → 状态机状态。
_STATUS_MAP = {
    "PENDING": LoginState.QR_READY,
    "SCANNED": LoginState.SCANNED,
    "SUCCESS": LoginState.SUCCESS,
    "EXPIRED": LoginState.EXPIRED,
    "FAILED": LoginState.FAILED,
}


@dataclass(frozen=True)
class LoginSession:
    login_id: str
    domain: str
    status: str
    qr_png: bytes | None = None
    session_id: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass
class _Entry:
    login: LoginSession
    handle: Any
    adapter: Any


SessionOpener = Callable[[str], Awaitable[Any]]
SessionCloser = Callable[..., Awaitable[str | None]]


class LoginManager:
    def __init__(
        self,
        *,
        adapters: list[Any],
        session_opener: SessionOpener,
        session_closer: SessionCloser,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
        ttl_seconds: int,
    ):
        self._adapters = list(adapters)
        self._open = session_opener
        self._close = session_closer
        self._clock = clock
        self._id_factory = id_factory
        self._ttl = ttl_seconds
        self._entries: dict[str, _Entry] = {}

    async def begin(self, url: str) -> LoginSession:
        domain = urlsplit(url).hostname or ""
        adapter = select_adapter(self._adapters, domain)
        if adapter is None:
            raise LoginError("LOGIN_INIT_FAILED", f"没有适配 {domain} 的登录适配器。")
        handle = await self._open(domain)
        await adapter.open_login(handle, url)
        qr = await adapter.capture_qr(handle)

        now = self._clock()
        login = LoginSession(
            login_id=self._id_factory(),
            domain=domain,
            status=LoginState.QR_READY,
            qr_png=qr,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl),
        )
        self._entries[login.login_id] = _Entry(login=login, handle=handle, adapter=adapter)
        return login

    async def poll(self, login_id: str) -> LoginSession | None:
        entry = self._entries.get(login_id)
        if entry is None:
            return None

        if entry.login.expires_at is not None and self._clock() >= entry.login.expires_at:
            return await self._finish(login_id, entry, LoginState.EXPIRED)

        raw = await entry.adapter.poll_status(entry.handle)
        status = _STATUS_MAP.get(raw, LoginState.QR_READY)

        if status == LoginState.SUCCESS:
            return await self._finish(login_id, entry, LoginState.SUCCESS)
        if status == LoginState.EXPIRED:
            return await self._finish(login_id, entry, LoginState.EXPIRED)
        # HC-011：适配器判定登录落到非允许域名等硬失败 → 关闭上下文、不封存 profile。
        if status == LoginState.FAILED:
            return await self._finish(login_id, entry, LoginState.FAILED)

        entry.login = replace(entry.login, status=status)
        return entry.login

    def get_qr_entry(self, login_id: str) -> LoginSession | None:
        """按 login_id 取当前在途登录条目（HC-QR-1/HC-QR-3）：登录结束后条目
        已从注册表移除，天然限定了可访问窗口，无需额外过期判断。"""
        entry = self._entries.get(login_id)
        return entry.login if entry is not None else None

    def get_qr_png(self, login_id: str) -> bytes | None:
        """供 /qr/{login_id} 只读端点使用（HC-QR-1）。"""
        login = self.get_qr_entry(login_id)
        return login.qr_png if login is not None else None

    async def cancel(self, login_id: str) -> bool:
        entry = self._entries.get(login_id)
        if entry is None:
            return False
        await self._finish(login_id, entry, LoginState.CANCELLED)
        return True

    async def _finish(
        self, login_id: str, entry: _Entry, status: str
    ) -> LoginSession:
        success = status == LoginState.SUCCESS
        session_id = await self._close(
            entry.handle, success=success, domain=entry.login.domain
        )
        final = replace(
            entry.login,
            status=status,
            session_id=session_id if success else None,
            qr_png=None,
        )
        self._entries.pop(login_id, None)
        return final
